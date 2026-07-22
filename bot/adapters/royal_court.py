"""Royal Court Theatre — Spektrix schedule + browser-read availability.

Spektrix's public API gives the authoritative performance list, but its
``isOnSale`` flag does not reflect whether seats remain (a sold-out show still
reports ``isOnSale: true``) and exposes no seat-availability endpoint. The real
availability is on the royalcourttheatre.com production page, which is
JavaScript-rendered behind bot protection.

So we render that page in a headless browser and read its dates-times list.
Each performance is a ``<li class="c-instance">`` with a ``<time>`` and one of:
  * "Book now" linking to ``/book/instance/{id}``            -> buyable
  * "Sold out *" linking to ``…&requireLogin=true``           -> Access-only
  * a disabled ``Sold out`` span with no link                 -> sold out
The buyable ``/book/instance/{id}`` numeric id equals the leading digits of the
Spektrix instance id, so we join the two: Spektrix supplies the exact date (with
year); the rendered page supplies real availability.

Crucially the page renders every performance as "Book now" first, then swaps
sold-out ones client-side, so the render must wait for network-idle before
reading — otherwise everything looks buyable. A blocked/failed render yields no
availability rather than a false alert.
"""
from __future__ import annotations

import logging
import re

from ..browser import fetch_json
from ..models import FetchResult, Performance
from .base import TheatreAdapter, host
from .util import format_display_date

log = logging.getLogger(__name__)

SYSTEM = "royalcourt"
API = f"https://system.spektrix.com/{SYSTEM}/api/v3"

_INSTANCE_BLOCK_RE = re.compile(r'<li class="c-instance[^"]*">.*?</li>', re.S)
_ACTION_RE = re.compile(r'c-instance__action">(.*?)</div>', re.S)
_BOOK_ID_RE = re.compile(r"/book/instance/(\d+)")
_BTN_TEXT_RE = re.compile(r'o-button__text"><span>([^<]+)</span>')


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _numeric_id(spektrix_id: str) -> str:
    m = re.match(r"\d+", spektrix_id or "")
    return m.group(0) if m else ""


def parse_event_match(events: list[dict], url: str) -> dict | None:
    """Pick the event whose slug matches the production URL slug."""
    m = re.search(r"/events/([^/?#]+)", url)
    target = _slug(m.group(1)) if m else ""
    if not target:
        return None
    for ev in events:
        if _slug(ev.get("name", "")) == target:
            return ev
    for ev in events:
        if target in _slug(ev.get("name", "")):
            return ev
    return None


def parse_rendered_availability(html: str) -> dict[str, bool]:
    """Map instance id (numeric) -> buyable-by-the-public, from the rendered
    dates-times list.

    On royalcourttheatre.com each performance renders a booking action:
      * "Book now" with a plain /book/instance/{id} link  -> general seats on
        sale = buyable.
      * "Sold out *" with a /book/instance/{id}&requireLogin=true link -> only
        Access-Members / returns remain = NOT buyable by the general public.
    We report available only for the first case.
    """
    out: dict[str, bool] = {}
    for block in _INSTANCE_BLOCK_RE.findall(html):
        mid = _BOOK_ID_RE.search(block)
        if not mid:
            continue
        action = _ACTION_RE.search(block)
        area = action.group(1) if action else block
        btn = _BTN_TEXT_RE.search(area)
        btn_text = btn.group(1).strip().lower() if btn else ""
        require_login = "requirelogin=true" in area.lower()
        out[mid.group(1)] = btn_text == "book now" and not require_login
    return out


def parse_instances(
    event_name: str,
    instances: list[dict],
    availability: dict[str, bool] | None = None,
) -> FetchResult:
    """Schedule from Spektrix; availability joined in by numeric instance id."""
    availability = availability or {}
    perfs: list[Performance] = []
    for inst in instances:
        if inst.get("cancelled"):
            continue
        start = inst.get("start", "")
        nid = _numeric_id(inst.get("id", ""))
        perfs.append(
            Performance(
                date_iso=start,
                display_date=format_display_date(start),
                available=availability.get(nid, False),
            )
        )
    perfs.sort(key=lambda p: p.date_iso)
    return FetchResult(title=event_name, performances=perfs)


class RoyalCourtAdapter(TheatreAdapter):
    name = "Royal Court Theatre"

    @classmethod
    def matches(cls, url: str) -> bool:
        return host(url) == "royalcourttheatre.com"

    async def fetch(self, url: str, browser) -> FetchResult:
        events = await fetch_json(f"{API}/events")
        if not isinstance(events, list):
            raise ValueError("Unexpected Spektrix events response")
        event = parse_event_match(events, url)
        if event is None:
            raise ValueError(
                "Could not find this production in the Royal Court listings."
            )
        instances = await fetch_json(f"{API}/events/{event['id']}/instances")
        if not isinstance(instances, list):
            raise ValueError("Unexpected Spektrix instances response")

        # Real availability from the rendered production page. The page first
        # renders every performance as "Book now", then JavaScript swaps
        # sold-out ones to a disabled "Sold out" span. We wait for the first
        # such swapped button to appear (bounded, not networkidle which can
        # hang) so we never read the premature all-"Book now" state. A fully
        # available show has no disabled buttons; the wait times out harmlessly
        # and we read it as-is. On any failure we keep the safe default.
        availability: dict[str, bool] = {}
        try:
            html = await browser.render_html(
                url,
                wait_selector="span.o-button--disabled",
                wait_timeout_ms=25000,
                settle_ms=3000,
            )
            availability = parse_rendered_availability(html)
            log.info(
                "RC render: %d instances with book links, %d buyable "
                "(disabled 'Sold out' spans on page: %d)",
                len(availability),
                sum(availability.values()),
                html.count("o-button--disabled"),
            )
        except Exception as exc:
            log.warning("RC render failed for %s: %s", url, exc)
        return parse_instances(
            event.get("name", "Royal Court production"), instances, availability
        )

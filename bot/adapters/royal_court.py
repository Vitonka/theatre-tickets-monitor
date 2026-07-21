"""Royal Court Theatre — Spektrix schedule + browser-read availability.

Spektrix's public API gives the authoritative performance list, but its
``isOnSale`` flag does not reflect whether seats remain (a sold-out show still
reports ``isOnSale: true``) and exposes no seat-availability endpoint. The real
availability is on the royalcourttheatre.com production page, which is
JavaScript-rendered behind bot protection.

So we render that page in a headless browser and read its dates-times list.
Each performance is a ``<li class="c-instance">`` with a ``<time>`` and, when
bookable, a "Book now" action linking to ``/book/instance/{id}``. That numeric
id equals the leading digits of the Spektrix instance id, so we join the two:
Spektrix supplies the exact date (with year); the rendered page supplies real
availability. A performance is available only when it has a book action, so a
blocked/failed render simply yields no availability (never a false alert).
"""
from __future__ import annotations

import re

from ..browser import fetch_json
from ..models import FetchResult, Performance
from .base import TheatreAdapter, host
from .util import format_display_date

SYSTEM = "royalcourt"
API = f"https://system.spektrix.com/{SYSTEM}/api/v3"

_INSTANCE_BLOCK_RE = re.compile(r'<li class="c-instance[^"]*">.*?</li>', re.S)
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
    """Map instance id (numeric) -> bookable, from the rendered dates-times list.

    Bookable = the instance shows a "Book"/"Buy" action. Sold-out performances
    render a "Sold out" / "Join the waiting list" label instead, so they don't
    match and stay unavailable.
    """
    out: dict[str, bool] = {}
    for block in _INSTANCE_BLOCK_RE.findall(html):
        mid = _BOOK_ID_RE.search(block)
        if not mid:
            continue
        btn = _BTN_TEXT_RE.search(block)
        btn_text = btn.group(1).lower() if btn else ""
        out[mid.group(1)] = "book" in btn_text or "buy" in btn_text
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

        # Real availability from the rendered production page. On any failure we
        # keep the safe default (unavailable) rather than guess.
        availability: dict[str, bool] = {}
        try:
            html = await browser.render_html(url, settle_ms=5000)
            availability = parse_rendered_availability(html)
        except Exception:
            pass
        return parse_instances(
            event.get("name", "Royal Court production"), instances, availability
        )

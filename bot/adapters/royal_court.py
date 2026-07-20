"""Royal Court Theatre — Spektrix schedule + browser-read availability.

The public Spektrix API gives the authoritative performance list, but its
``isOnSale`` flag only means "open for sale", not that seats remain — a
sold-out-but-listed show still reports ``isOnSale: true``. Spektrix exposes no
public seat-availability endpoint, and the royalcourttheatre.com booking
calendar is JavaScript-rendered behind bot protection.

So we take the schedule from Spektrix and read *real* availability by rendering
the production page in a headless browser and classifying the visible booking
text per date (see ``availability.annotate``). This is defensive: a date is
only marked available on a clear "bookable"/price signal, so a failed or
blocked render yields no false alerts (everything stays unavailable).

Note: the render path can't be exercised in every environment; use
``scripts/probe.py render <url>`` on the host to confirm/tune wording in
``availability.py`` if Royal Court alerts look off.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ..browser import fetch_json
from ..models import FetchResult, Performance
from .availability import annotate
from .base import TheatreAdapter, host
from .util import format_display_date, price_range

SYSTEM = "royalcourt"
API = f"https://system.spektrix.com/{SYSTEM}/api/v3"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


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


def parse_instances(event_name: str, instances: list[dict]) -> FetchResult:
    """Schedule from Spektrix. Availability defaults to False here; the real
    value is overlaid from the rendered booking page in ``fetch``."""
    perfs: list[Performance] = []
    for inst in instances:
        if inst.get("cancelled"):
            continue
        start = inst.get("start", "")
        cheapest = inst.get("cheapestTicketPrice") or {}
        price = ""
        if isinstance(cheapest, dict) and cheapest.get("value") is not None:
            price = price_range(f"£{cheapest['value']}")
        perfs.append(
            Performance(
                date_iso=start,
                display_date=format_display_date(start),
                available=False,
                price_text=price,
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
        instances = await fetch_json(
            f"{API}/events/{event['id']}/instances?cheapestTicketPrice=true"
        )
        if not isinstance(instances, list):
            raise ValueError("Unexpected Spektrix instances response")
        base = parse_instances(event.get("name", "Royal Court production"), instances)

        # Overlay real availability from the rendered production page. On any
        # failure we keep the safe default (unavailable) rather than guess.
        try:
            html = await browser.render_html(url, settle_ms=5000)
            text = BeautifulSoup(html, "html.parser").get_text(" ")
            performances = annotate(base.performances, text)
        except Exception:
            performances = base.performances
        return FetchResult(title=base.title, performances=performances)

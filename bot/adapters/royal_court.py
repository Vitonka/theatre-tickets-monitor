"""Royal Court Theatre — backed by the Spektrix ticketing platform.

The public site (royalcourttheatre.com) sits behind Cloudflare and its booking
calendar is JS-rendered, but the underlying Spektrix system exposes a public
read-only JSON API that needs no browser:

    https://system.spektrix.com/royalcourt/api/v3/events
    https://system.spektrix.com/royalcourt/api/v3/events/{id}/instances

We match the production by its URL slug against the event list, then read the
per-performance instances. ``isOnSale`` is Spektrix's public "this performance
is open for sale" flag — see the module note on its limits.
"""
from __future__ import annotations

import re

from ..browser import fetch_json
from ..models import FetchResult, Performance
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
    # Looser fallback: slug is a prefix/substring of the event name slug.
    for ev in events:
        if target in _slug(ev.get("name", "")):
            return ev
    return None


def parse_instances(event_name: str, instances: list[dict]) -> FetchResult:
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
                available=bool(inst.get("isOnSale")),
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
        return parse_instances(event.get("name", "Royal Court production"), instances)

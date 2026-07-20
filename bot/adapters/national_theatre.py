"""National Theatre — nationaltheatre.org.uk.

The production page is a JS app and carries no per-date availability in its
static HTML, but the site is driven by a public JSON API that returns every
performance with its booking status and prices — no browser required:

    https://events.nationaltheatre.org.uk/api/v1/events/{productionId}

Each ``instance`` (performance) has a ``datetime`` (UTC), a ``bookingStatus``
("auto" = on sale / bookable, anything else = not bookable, e.g.
"nonbookable"), a ``bookingURL`` and a ``prices`` list keyed by mode-of-sale.

The numeric production id is read from the production page's booking links
(``tickets.nationaltheatre.org.uk/{productionId}/{performanceId}``); if the
page exposes none, we fall back to matching the production by slug against the
API's on-sale listing.
"""
from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from ..browser import fetch_html, fetch_json
from ..models import FetchResult, Performance
from .base import TheatreAdapter, host
from .util import format_display_date, price_range

API = "https://events.nationaltheatre.org.uk/api/v1"
LONDON = ZoneInfo("Europe/London")
_BOOKING_ID_RE = re.compile(r"tickets\.nationaltheatre\.org\.uk/(\d+)/\d+")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _local(iso_utc: str) -> tuple[str, str]:
    """'2026-07-20T18:30:00Z' -> ('2026-07-20T19:30:00', 'Mon 20 Jul 2026, 7:30pm').

    NT datetimes are UTC; convert to London local so the alert matches the
    time a customer sees on the site.
    """
    try:
        dt = datetime.fromisoformat(iso_utc.replace("Z", "+00:00")).astimezone(LONDON)
    except ValueError:
        return iso_utc, iso_utc
    local_iso = dt.strftime("%Y-%m-%dT%H:%M:%S")
    return local_iso, format_display_date(local_iso)


def _instance_price(instance: dict, mode_of_sale: str) -> str:
    prices = instance.get("prices") or []
    tier = [p for p in prices if str(p.get("mos")) == mode_of_sale] or prices
    return price_range(" ".join(f"£{p['price']}" for p in tier if p.get("price")))


def parse_event(event: dict) -> FetchResult:
    """Turn the API event payload into performances with availability."""
    title = event.get("title") or "National Theatre production"
    mode_of_sale = str(event.get("modeOfSale", ""))
    perfs: list[Performance] = []
    for inst in event.get("instances", []):
        local_iso, display = _local(inst.get("datetime", ""))
        perfs.append(
            Performance(
                date_iso=local_iso,
                display_date=display,
                available=inst.get("bookingStatus") == "auto",
                price_text=_instance_price(inst, mode_of_sale),
                book_url=inst.get("bookingURL") or "",
            )
        )
    perfs.sort(key=lambda p: p.date_iso)
    return FetchResult(title=title, performances=perfs)


async def _resolve_event_id(url: str) -> str | None:
    # Preferred: the numeric id embedded in the page's booking links.
    try:
        html = await fetch_html(url)
        m = _BOOKING_ID_RE.search(html)
        if m:
            return m.group(1)
    except Exception:
        pass
    # Fallback: match the URL slug against the API's on-sale listing.
    slug_m = re.search(r"/productions/([^/?#]+)", url)
    slug = slug_m.group(1) if slug_m else ""
    if not slug:
        return None
    listing = await fetch_json(f"{API}/events/")
    if isinstance(listing, list):
        for ev in listing:
            if _slug(ev.get("title", "")) == slug:
                return str(ev.get("_id"))
    return None


class NationalTheatreAdapter(TheatreAdapter):
    name = "National Theatre"

    @classmethod
    def matches(cls, url: str) -> bool:
        return host(url) == "nationaltheatre.org.uk"

    async def fetch(self, url: str, browser) -> FetchResult:
        event_id = await _resolve_event_id(url)
        if not event_id:
            raise ValueError(
                "Could not find this production on the National Theatre site."
            )
        event = await fetch_json(f"{API}/events/{event_id}")
        if not isinstance(event, dict) or "instances" not in event:
            raise ValueError("Unexpected National Theatre API response")
        return parse_event(event)

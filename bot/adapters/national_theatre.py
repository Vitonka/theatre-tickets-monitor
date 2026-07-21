"""National Theatre — nationaltheatre.org.uk.

Two data sources are combined:

* The public events API gives the authoritative schedule and prices:
      https://events.nationaltheatre.org.uk/api/v1/events/{productionId}
  Each instance has a ``datetime`` (UTC), ``bookingURL`` and ``prices`` — but
  its ``bookingStatus`` ("auto") only means "on public sale", NOT that seats
  are actually available (a sold-out show still reports "auto").

* The real, seat-level availability the customer sees comes from the Tessitura
  (TNEW) booking page, whose performance <select> lists every performance as
      <option value=".../{productionId}/{performanceId}">Date (Sold out)?</option>
  The "(Sold out)" suffix is the ground truth. We fetch it once per show and
  overlay it onto the schedule, matched by performance id.

The numeric production id comes from the production page's booking links, or a
slug match against the API's on-sale listing when the page exposes none.
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
TNEW = "https://tickets.nationaltheatre.org.uk"
LONDON = ZoneInfo("Europe/London")
_BOOKING_ID_RE = re.compile(r"tickets\.nationaltheatre\.org\.uk/(\d+)/\d+")
_TNEW_OPTION_RE = re.compile(
    r'<option value="https://tickets\.nationaltheatre\.org\.uk/\d+/(\d+)"[^>]*>'
    r"([^<]*)</option>"
)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _perf_id(booking_url: str) -> str:
    m = re.search(r"/(\d+)(?:\?|$)", booking_url or "")
    return m.group(1) if m else ""


def _local(iso_utc: str) -> tuple[str, str]:
    """UTC ISO -> (local-naive ISO, human display) in London time."""
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


def parse_tnew_availability(html: str) -> dict[str, bool]:
    """Map performance id -> is_available from the TNEW performance <select>."""
    out: dict[str, bool] = {}
    for perf_id, label in _TNEW_OPTION_RE.findall(html):
        out[perf_id] = "sold out" not in label.lower()
    return out


def parse_event(event: dict, availability: dict[str, bool]) -> FetchResult:
    """Combine the API schedule with real TNEW availability."""
    title = event.get("title") or "National Theatre production"
    mode_of_sale = str(event.get("modeOfSale", ""))
    perfs: list[Performance] = []
    for inst in event.get("instances", []):
        local_iso, display = _local(inst.get("datetime", ""))
        perf_id = _perf_id(inst.get("bookingURL", ""))
        # Available only when the TNEW booking list says this performance is
        # not sold out. Unknown id (not on sale there) => treat as unavailable.
        available = availability.get(perf_id, False)
        perfs.append(
            Performance(
                date_iso=local_iso,
                display_date=display,
                available=available,
                price_text=_instance_price(inst, mode_of_sale),
                book_url=inst.get("bookingURL") or "",
            )
        )
    perfs.sort(key=lambda p: p.date_iso)
    return FetchResult(title=title, performances=perfs)


async def _resolve_event_id(url: str) -> str | None:
    try:
        html = await fetch_html(url)
        m = _BOOKING_ID_RE.search(html)
        if m:
            return m.group(1)
    except Exception:
        pass
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
        # Real availability from the TNEW booking page. Fast path is a plain
        # HTTP fetch; if that returns no options (National Theatre gates TNEW
        # behind a queue-it waiting room that scripted requests can't pass) we
        # retry with the headless browser, which does pass it. If both fail we
        # keep "no availability" rather than emit false alerts.
        availability: dict[str, bool] = {}
        try:
            availability = parse_tnew_availability(await fetch_html(f"{TNEW}/{event_id}"))
        except Exception:
            pass
        if not availability:
            try:
                html = await browser.render_html(f"{TNEW}/{event_id}", settle_ms=6000)
                availability = parse_tnew_availability(html)
            except Exception:
                pass
        return parse_event(event, availability)

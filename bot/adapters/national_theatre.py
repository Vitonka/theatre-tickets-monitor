"""National Theatre — nationaltheatre.org.uk.

Real per-performance availability lives only in the Tessitura (TNEW) seat page:
neither the events API (every instance is ``bookingStatus:"auto"``) nor the
production page nor the TNEW performance list distinguishes an on-sale-but-sold-
out performance. But the individual seat page does, unambiguously:

    available  -> contains "Best available"        (seat map is offered)
    sold out   -> contains "Not currently available"

So we take the schedule from the events API and check each performance's seat
page. TNEW sits behind a queue-it waiting room; a plain HTTP fetch passes it in
most environments, and we fall back to the headless browser (which always
passes it) for any performance that comes back ambiguous.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from ..browser import fetch_html, fetch_json
from ..models import FetchResult, Performance
from .base import TheatreAdapter, host

log = logging.getLogger(__name__)

API = "https://events.nationaltheatre.org.uk/api/v1"
TNEW = "https://tickets.nationaltheatre.org.uk"
LONDON = ZoneInfo("Europe/London")
_BOOKING_ID_RE = re.compile(r"tickets\.nationaltheatre\.org\.uk/(\d+)/\d+")


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
    hour = dt.hour % 12 or 12
    minute = f":{dt.minute:02d}" if dt.minute else ""
    ampm = "am" if dt.hour < 12 else "pm"
    return local_iso, f"{dt:%a} {dt.day} {dt:%b %Y}, {hour}{minute}{ampm}"


def perf_available_from_page(html: str) -> bool | None:
    """True/False from a TNEW seat page; None when the signal is absent
    (e.g. a queue-it holding page) so the caller can retry via the browser."""
    low = html.lower()
    if "not currently available" in low:
        return False
    if "best available" in low:
        return True
    return None


async def _resolve_event_id(url: str) -> str | None:
    try:
        m = _BOOKING_ID_RE.search(await fetch_html(url))
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


async def _http_html(u: str) -> str | None:
    try:
        return await fetch_html(u)
    except Exception:
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
        title = event.get("title") or "National Theatre production"
        instances = event["instances"]
        seat_urls = [
            inst.get("bookingURL") or f"{TNEW}/{event_id}/{_perf_id(inst.get('bookingURL',''))}"
            for inst in instances
        ]

        # Phase 1: fast concurrent HTTP checks.
        htmls = await asyncio.gather(*[_http_html(u) for u in seat_urls])
        avail: list[bool | None] = [
            perf_available_from_page(h) if isinstance(h, str) else None for h in htmls
        ]

        http_unknown = sum(1 for r in avail if r is None)
        log.info(
            "NT %s: %d performances; HTTP resolved %d, %d need browser "
            "(queue-it). If this is high, the plain fetch is being queued.",
            title, len(instances), len(instances) - http_unknown, http_unknown,
        )

        # Phase 2: browser fallback (passes queue-it) for anything still unknown,
        # done sequentially to bound memory on small hosts. Use network-idle so
        # the queue-it redirect chain completes before we read the seat page.
        for idx, res in enumerate(avail):
            if res is not None:
                continue
            try:
                html = await browser.render_html(
                    seat_urls[idx], wait_until="networkidle", settle_ms=3000
                )
                avail[idx] = perf_available_from_page(html)
                log.info("NT browser fallback %s -> %s", seat_urls[idx][-12:], avail[idx])
            except Exception as exc:
                log.warning("NT browser fallback failed %s: %s", seat_urls[idx][-12:], exc)

        perfs: list[Performance] = []
        for inst, res in zip(instances, avail):
            local_iso, display = _local(inst.get("datetime", ""))
            perfs.append(
                Performance(
                    date_iso=local_iso,
                    display_date=display,
                    available=bool(res),
                    book_url=inst.get("bookingURL") or "",
                )
            )
        perfs.sort(key=lambda p: p.date_iso)
        return FetchResult(title=title, performances=perfs)

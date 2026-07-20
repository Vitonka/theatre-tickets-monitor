"""National Theatre — nationaltheatre.org.uk.

The production page blocks bare requests (403) without a realistic User-Agent,
but with one it serves static HTML containing schema.org ``Event`` blocks — one
per performance — which give the authoritative list of dates. Prices appear as
a range in the page copy. Per-date availability is served by the TNEW booking
widget (tickets.nationaltheatre.org.uk), so we render the page with a browser
and classify availability from the visible booking text.
"""
from __future__ import annotations

from bs4 import BeautifulSoup

from ..models import FetchResult, Performance
from .availability import annotate
from .base import TheatreAdapter, extract_ldjson, host
from .util import format_display_date, price_range


def parse_dates(html: str) -> FetchResult:
    """Authoritative title + performance dates from the static HTML."""
    title = "National Theatre production"
    perfs: list[Performance] = []
    seen: set[str] = set()
    for item in extract_ldjson(html):
        if item.get("@type") != "Event":
            continue
        title = item.get("name") or title
        start = item.get("startDate") or ""
        if not start or start in seen:
            continue
        seen.add(start)
        # Sold state per-date is not in the static HTML; default False so we
        # only ever alert on a positive signal from the rendered booking page.
        perfs.append(
            Performance(
                date_iso=start,
                display_date=format_display_date(start),
                available=False,
            )
        )
    perfs.sort(key=lambda p: p.date_iso)
    prices = price_range(BeautifulSoup(html, "html.parser").get_text(" "))
    if prices:
        perfs = [
            Performance(p.date_iso, p.display_date, p.available, prices, p.book_url)
            for p in perfs
        ]
    return FetchResult(title=title, performances=perfs)


class NationalTheatreAdapter(TheatreAdapter):
    name = "National Theatre"

    @classmethod
    def matches(cls, url: str) -> bool:
        return host(url) == "nationaltheatre.org.uk"

    async def fetch(self, url: str, browser) -> FetchResult:
        # Render (rather than plain GET) so the booking widget's availability
        # text is present for classification.
        html = await browser.render_html(url, settle_ms=4000)
        result = parse_dates(html)
        visible = BeautifulSoup(html, "html.parser").get_text(" ")
        performances = annotate(result.performances, visible)
        return FetchResult(title=result.title, performances=performances)

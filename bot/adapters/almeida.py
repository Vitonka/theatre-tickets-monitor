"""Almeida Theatre — almeida.co.uk.

The production page serves static HTML with the title and a production-level
"Sold Out" banner, but individual performance dates and their availability load
client-side on the calendar view (``/calendar/?e=<slug>``). We read the title
and banner from the production page, then render the calendar to extract dated
performances and classify each one's availability.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ..models import FetchResult, Performance
from .availability import classify_window
from .base import TheatreAdapter, host
from .util import format_display_date

# "Wed 9 Sep 2026", "9 September 2026", optionally with a time.
_DATE_RE = re.compile(
    r"(?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\s+)?"
    r"(\d{1,2})\s+"
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+"
    r"(\d{4})"
    r"(?:[^0-9]{0,16}?(\d{1,2})[:.](\d{2})\s*(am|pm)?)?",
    re.IGNORECASE,
)
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def slug_from_url(url: str) -> str:
    m = re.search(r"/whats-on/([^/?#]+)", url)
    return m.group(1) if m else ""


def calendar_url(url: str) -> str:
    slug = slug_from_url(url)
    return f"https://almeida.co.uk/calendar/?e={slug}" if slug else url


def parse_production(html: str) -> tuple[str, bool]:
    """Return (title, production_marked_sold_out) from the production page."""
    soup = BeautifulSoup(html, "html.parser")
    title = "Almeida production"
    og = soup.find("meta", attrs={"property": "og:title"})
    if og and og.get("content"):
        title = og["content"].split("|")[0].strip()
    elif soup.title and soup.title.string:
        title = soup.title.string.split("|")[0].strip()
    sold_out = "sold out" in soup.get_text(" ").lower()
    return title, sold_out


def parse_calendar(rendered_text: str, title: str) -> list[Performance]:
    """Extract dated performances and their availability from calendar text."""
    flat = re.sub(r"\s+", " ", rendered_text)
    matches = list(_DATE_RE.finditer(flat))
    perfs: list[Performance] = []
    seen: set[str] = set()
    for idx, m in enumerate(matches):
        day, mon, year = int(m.group(1)), _MONTHS[m.group(2)[:3].lower()], m.group(3)
        hh, mm = m.group(4), m.group(5)
        if hh is not None:
            hour = int(hh)
            if (m.group(6) or "").lower() == "pm" and hour != 12:
                hour += 12
            if (m.group(6) or "").lower() == "am" and hour == 12:
                hour = 0
            iso = f"{year}-{mon:02d}-{day:02d}T{hour:02d}:{int(mm):02d}:00"
        else:
            iso = f"{year}-{mon:02d}-{day:02d}T00:00:00"
        if iso in seen:
            continue
        seen.add(iso)
        # Scope the availability window to this performance only: stop at the
        # next date so a sold-out entry can't inherit the next one's price.
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(flat)
        window = flat[m.end(): min(end, m.end() + 200)]
        avail, price = classify_window(window)
        perfs.append(
            Performance(
                date_iso=iso,
                display_date=format_display_date(iso),
                available=bool(avail),
                price_text=price,
            )
        )
    perfs.sort(key=lambda p: p.date_iso)
    return perfs


class AlmeidaAdapter(TheatreAdapter):
    name = "Almeida Theatre"

    @classmethod
    def matches(cls, url: str) -> bool:
        return host(url) == "almeida.co.uk"

    async def fetch(self, url: str, browser) -> FetchResult:
        prod_html = await browser.render_html(url, settle_ms=2000)
        title, _ = parse_production(prod_html)
        cal_html = await browser.render_html(calendar_url(url), settle_ms=4500)
        text = BeautifulSoup(cal_html, "html.parser").get_text(" ")
        perfs = parse_calendar(text, title)
        return FetchResult(title=title, performances=perfs)

"""Almeida Theatre — almeida.co.uk.

The calendar is rendered client-side from a WordPress admin-ajax endpoint that
returns an HTML fragment per performance:

    https://almeida.co.uk/admin/wp-admin/admin-ajax.php?action=calendar&e=<slug>

The ``e=<slug>`` parameter is cosmetic — the endpoint returns *every* Almeida
performance — so we filter by the show whose ``event-link`` href matches the
monitored production's slug. Each fragment carries the real availability the
customer sees, as a CSS state on the button/indicator:

    c-availability-indicator--sold-out   -> sold out
    c-btn--book / --limited / --good      -> bookable

No browser required.
"""
from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup

from ..browser import fetch_json
from ..models import FetchResult, Performance
from .base import TheatreAdapter, host
from .util import format_display_date, price_range

AJAX = "https://almeida.co.uk/admin/wp-admin/admin-ajax.php?action=calendar&e="


def slug_from_url(url: str) -> str:
    m = re.search(r"/(?:whats-on|calendar)/?\?e=([^/?#&]+)", url) or re.search(
        r"/whats-on/([^/?#]+)", url
    )
    return m.group(1) if m else ""


def _instance_slug(fragment_soup: BeautifulSoup) -> str:
    a = fragment_soup.select_one("a.c-calendar-instance__event-link")
    if not a or not a.get("href"):
        return ""
    m = re.search(r"/whats-on/([^/?#]+)", a["href"])
    return m.group(1) if m else ""


def parse_calendar(instances: list[str], slug: str) -> FetchResult:
    """Parse admin-ajax fragments into performances for one production."""
    title = "Almeida production"
    perfs: list[Performance] = []
    for fragment in instances:
        soup = BeautifulSoup(fragment, "html.parser")
        if _instance_slug(soup) != slug:
            continue
        h3 = soup.select_one(".c-calendar-instance__title")
        if h3 and h3.get_text(strip=True):
            title = h3.get_text(strip=True)
        time_el = soup.select_one("time.c-calendar-instance__time")
        raw_dt = (time_el.get("datetime") if time_el else "") or ""
        iso = raw_dt.strip().replace(" ", "T")

        sold_out = bool(soup.select_one(".c-availability-indicator--sold-out")) or bool(
            soup.select_one(".c-btn--disabled")
        )
        bookable = bool(soup.select_one(".c-btn--book"))
        available = bookable and not sold_out
        perfs.append(
            Performance(
                date_iso=iso,
                display_date=format_display_date(iso),
                available=available,
                price_text=price_range(soup.get_text(" ")),
            )
        )
    perfs.sort(key=lambda p: p.date_iso)
    return FetchResult(title=title, performances=perfs)


class AlmeidaAdapter(TheatreAdapter):
    name = "Almeida Theatre"

    @classmethod
    def matches(cls, url: str) -> bool:
        return host(url) == "almeida.co.uk"

    async def fetch(self, url: str, browser) -> FetchResult:
        slug = slug_from_url(url)
        if not slug:
            raise ValueError("Could not read the production slug from that URL.")
        data = await fetch_json(f"{AJAX}{slug}")
        instances = data.get("instances") if isinstance(data, dict) else None
        if not isinstance(instances, list):
            raise ValueError("Unexpected Almeida calendar response")
        result = parse_calendar(instances, slug)
        if not result.performances:
            raise ValueError(
                "No performances found for this production on the Almeida calendar."
            )
        return result

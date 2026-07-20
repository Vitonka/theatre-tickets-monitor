"""Core data types shared across adapters, storage and the bot."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Performance:
    """A single performance (one date/time) of a production.

    ``key`` is the stable identity used for change detection: two fetches that
    describe the same performance must produce the same key. We derive it from
    the ISO date-time so it is stable even if wording around it changes.
    """

    date_iso: str          # e.g. "2026-09-11T19:30:00" (local theatre time)
    display_date: str      # human string, e.g. "Fri 11 Sep 2026, 7:30pm"
    available: bool        # True when seats can be bought right now
    price_text: str = ""   # e.g. "£45" or "£25–£65"; "" when unknown
    book_url: str = ""     # deep link to buy, when the site exposes one

    @property
    def key(self) -> str:
        return self.date_iso or self.display_date


@dataclass(frozen=True)
class FetchResult:
    """What an adapter returns for a monitored URL."""

    title: str
    performances: list[Performance]

    @property
    def available(self) -> list[Performance]:
        return [p for p in self.performances if p.available]

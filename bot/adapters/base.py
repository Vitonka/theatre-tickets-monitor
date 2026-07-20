"""Adapter contract and registry.

A ``TheatreAdapter`` knows how to turn one production URL into a
``FetchResult`` (title + list of performances with availability/price). Adding
support for a new theatre means writing one subclass and listing it in
``bot/adapters/__init__.py`` — nothing else in the codebase changes.

Each adapter separates:

* ``fetch``  – does the network I/O (HTTP or headless browser), then delegates
* ``parse`` – a *pure* function over the fetched payload, so it can be unit
  tested against saved fixtures without touching the network.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from ..browser import BrowserManager
from ..models import FetchResult


class TheatreAdapter(ABC):
    #: Human-readable theatre name, shown in the bot UI.
    name: str = "Theatre"

    @classmethod
    @abstractmethod
    def matches(cls, url: str) -> bool:
        """Return True if this adapter handles ``url`` (matched by domain)."""

    @abstractmethod
    async def fetch(self, url: str, browser: BrowserManager) -> FetchResult:
        """Fetch and parse the current state of the production at ``url``."""


def host(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def extract_ldjson(html: str) -> list[dict]:
    """Return every JSON-LD object embedded in ``html`` (flattened)."""
    soup = BeautifulSoup(html, "html.parser")
    out: list[dict] = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text() or ""
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        for item in data if isinstance(data, list) else [data]:
            if isinstance(item, dict):
                out.append(item)
    return out

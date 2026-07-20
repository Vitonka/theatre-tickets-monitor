"""Adapter registry.

To support a new theatre: add a ``TheatreAdapter`` subclass in its own module
and append an instance to ``ADAPTERS`` below.
"""
from __future__ import annotations

from .almeida import AlmeidaAdapter
from .base import TheatreAdapter
from .national_theatre import NationalTheatreAdapter
from .royal_court import RoyalCourtAdapter

ADAPTERS: list[TheatreAdapter] = [
    AlmeidaAdapter(),
    RoyalCourtAdapter(),
    NationalTheatreAdapter(),
]


def resolve(url: str) -> TheatreAdapter | None:
    """Return the adapter that handles ``url``, or None if unsupported."""
    for adapter in ADAPTERS:
        if adapter.matches(url):
            return adapter
    return None


def supported_theatres() -> list[str]:
    return [a.name for a in ADAPTERS]


__all__ = ["TheatreAdapter", "ADAPTERS", "resolve", "supported_theatres"]

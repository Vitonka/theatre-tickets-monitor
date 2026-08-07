"""Adapter registry.

Only theatres listed in ``ADAPTERS`` are active. Right now that's **Almeida**
only — it uses a plain JSON endpoint (no browser), so the bot is lightweight and
reliable. The National Theatre and Royal Court adapters still live in this
package (``national_theatre.py``, ``royal_court.py``) and can be switched back
on by importing them and adding an instance below — but they need the headless
browser (re-add ``playwright`` to requirements and the Playwright base image),
so they're intentionally disabled until each is verified end-to-end.
"""
from __future__ import annotations

from .almeida import AlmeidaAdapter
from .base import TheatreAdapter

ADAPTERS: list[TheatreAdapter] = [
    AlmeidaAdapter(),
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

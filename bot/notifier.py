"""Formatting of availability alerts."""
from __future__ import annotations

from html import escape

from .models import Performance
from .storage import Monitor

MAX_LINES = 12


def format_alert(monitor: Monitor, performances: list[Performance]) -> str:
    """Build the HTML message body for newly-available performances."""
    lines = [
        f"🎭 <b>Tickets available</b> — {escape(monitor.title)} "
        f"({escape(monitor.theatre)})"
    ]
    for p in performances[:MAX_LINES]:
        price = f" — {escape(p.price_text)}" if p.price_text else ""
        lines.append(f"• {escape(p.display_date)}{price}")
    if len(performances) > MAX_LINES:
        lines.append(f"…and {len(performances) - MAX_LINES} more")
    lines.append(f'\n<a href="{escape(monitor.url, quote=True)}">Book / view</a>')
    return "\n".join(lines)

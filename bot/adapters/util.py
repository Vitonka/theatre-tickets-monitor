"""Small parsing helpers shared by adapters."""
from __future__ import annotations

import re
from datetime import datetime

_PRICE_RE = re.compile(r"£\s?\d+(?:\.\d{2})?")


def format_display_date(iso: str) -> str:
    """'2026-09-11T19:30:00' -> 'Fri 11 Sep 2026, 7:30pm'. Best effort."""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso
    hour = dt.hour % 12 or 12
    minute = f":{dt.minute:02d}" if dt.minute else ""
    ampm = "am" if dt.hour < 12 else "pm"
    return f"{dt:%a} {dt.day} {dt:%b %Y}, {hour}{minute}{ampm}"


def price_range(text: str) -> str:
    """Extract a compact '£min–£max' (or single '£x') from a blob of text."""
    values = []
    for m in _PRICE_RE.findall(text):
        try:
            values.append(float(m.replace("£", "").strip()))
        except ValueError:
            pass
    if not values:
        return ""
    lo, hi = min(values), max(values)

    def fmt(v: float) -> str:
        return f"£{int(v)}" if v.is_integer() else f"£{v:.2f}"

    return fmt(lo) if lo == hi else f"{fmt(lo)}–{fmt(hi)}"

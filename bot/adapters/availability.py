"""Heuristic availability detection over a rendered booking DOM.

The three theatres render their per-date booking UI with different platforms
(TNEW/Tessitura, Spektrix, ATG), but all share the same visual grammar: an
available performance shows a price and/or a "Book"/"Add" control, while an
unavailable one shows a "Sold Out" / "No availability" / "Returns only" style
marker (or a disabled control).

Rather than bind to fragile per-platform CSS classes, we scan the *text window*
around each known performance date and classify it. This keeps the adapters
robust to markup churn; the vocabulary below is the single place to tune if a
theatre uses different wording.
"""
from __future__ import annotations

import re
from datetime import datetime

from ..models import Performance
from .util import price_range

SOLD_OUT_MARKERS = (
    "sold out",
    "no availability",
    "not available",
    "unavailable",
    "fully booked",
    "returns only",
    "join the waiting list",
    "waiting list",
)
AVAILABLE_MARKERS = (
    "book now",
    "book tickets",
    "add to basket",
    "add to cart",
    "buy tickets",
    "select tickets",
    "limited availability",
    "few tickets",
    "good availability",
)


def classify_window(text: str) -> tuple[bool | None, str]:
    """Classify a chunk of visible text near a date.

    Returns ``(available, price_text)`` where ``available`` is True/False, or
    ``None`` when the text gives no usable signal (caller decides the default).
    """
    low = text.lower()
    price = price_range(text)
    sold_out = any(m in low for m in SOLD_OUT_MARKERS)
    available = any(m in low for m in AVAILABLE_MARKERS) or bool(price)
    if sold_out and not available:
        return False, price
    if available and not sold_out:
        return True, price
    if sold_out and available:
        # Mixed signals (e.g. "limited availability £45" beside a sold-out
        # sibling). Presence of a live price wins.
        return (True, price) if price else (False, "")
    return None, price


_WS = re.compile(r"\s+")


def annotate(performances: list[Performance], visible_text: str) -> list[Performance]:
    """Re-classify ``performances`` using the booking page's visible text.

    For each performance we locate its human date string in the text and read a
    window around it. Performances we cannot locate keep their incoming state.
    """
    flat = _WS.sub(" ", visible_text)
    low = flat.lower()
    out: list[Performance] = []
    for p in performances:
        pos = _locate(low, _date_needles(p))
        if pos == -1:
            out.append(p)
            continue
        window = flat[pos: pos + 220]
        avail, price = classify_window(window)
        out.append(
            Performance(
                date_iso=p.date_iso,
                display_date=p.display_date,
                available=p.available if avail is None else avail,
                price_text=price or p.price_text,
                book_url=p.book_url,
            )
        )
    return out


def _locate(low_text: str, needles: list[str]) -> int:
    """First position of any needle, requiring a non-digit boundary before a
    leading day number so "5 sep" doesn't match inside "15 sep"."""
    for n in needles:
        m = re.search(r"(?<!\d)" + re.escape(n), low_text)
        if m:
            return m.start()
    return -1


def _date_needles(p: Performance) -> list[str]:
    """Lower-cased, year-qualified date fragments, most specific first."""
    needles: list[str] = []
    try:
        dt = datetime.fromisoformat(p.date_iso)
    except ValueError:
        dt = None
    if dt:
        needles.append(dt.strftime("%Y-%m-%d"))
        needles.append(f"{dt.day} {dt.strftime('%b').lower()} {dt.year}")
        needles.append(f"{dt.day} {dt.strftime('%B').lower()} {dt.year}")
    m = re.search(r"(\d{1,2})\s+([A-Za-z]{3,})\s+(\d{4})", p.display_date)
    if m:
        needles.append(f"{int(m.group(1))} {m.group(2).lower()} {m.group(3)}")
    return list(dict.fromkeys(needles))

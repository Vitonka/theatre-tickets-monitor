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
        needles = _date_needles(p)
        pos = next((low.find(n) for n in needles if low.find(n) != -1), -1)
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


def _date_needles(p: Performance) -> list[str]:
    """Lower-cased date fragments to search for, most specific first."""
    needles = []
    iso = p.date_iso[:10]
    if iso:
        needles.append(iso)
    # "11 sep 2026" style, taken from the display date if present.
    m = re.search(r"(\d{1,2})\s+([A-Za-z]{3,})\s+(\d{4})", p.display_date)
    if m:
        needles.append(f"{int(m.group(1))} {m.group(2).lower()} {m.group(3)}")
    return needles

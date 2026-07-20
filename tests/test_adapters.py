"""Parser tests against real fixtures captured from the live sites."""
import json
import pathlib

import pytest

from bot.adapters.almeida import parse_calendar, parse_production, calendar_url
from bot.adapters.availability import annotate, classify_window
from bot.adapters.national_theatre import parse_event
from bot.adapters.royal_court import parse_event_match, parse_instances
from bot.adapters.util import format_display_date, price_range
from bot.models import Performance

FIX = pathlib.Path(__file__).parent / "fixtures"


def read(name: str) -> str:
    return (FIX / name).read_text()


# ----- util ---------------------------------------------------------------
def test_format_display_date():
    assert format_display_date("2026-09-11T19:30:00") == "Fri 11 Sep 2026, 7:30pm"
    assert format_display_date("2026-09-12T14:00:00") == "Sat 12 Sep 2026, 2pm"


def test_price_range():
    assert price_range("tickets from £30 up to £120 today") == "£30–£120"
    assert price_range("flat £45 seats") == "£45"
    assert price_range("no prices here") == ""


# ----- availability heuristic --------------------------------------------
def test_classify_window():
    assert classify_window("Sold Out")[0] is False
    assert classify_window("Book now £45")[0] is True
    assert classify_window("just some text")[0] is None
    # mixed: live price wins
    assert classify_window("Limited availability sold out elsewhere £30")[0] is True


def test_annotate_flips_state_from_visible_text():
    perfs = [
        Performance("2026-09-11T19:30:00", "Fri 11 Sep 2026, 7:30pm", False),
        Performance("2026-09-12T19:30:00", "Sat 12 Sep 2026, 7:30pm", False),
    ]
    text = (
        "Performance 2026-09-11 Book now £45 . "
        "Performance 2026-09-12 Sold Out ."
    )
    out = annotate(perfs, text)
    assert out[0].available is True and out[0].price_text == "£45"
    assert out[1].available is False


# ----- Royal Court (Spektrix) --------------------------------------------
def test_royalcourt_event_match_and_instances():
    events = json.loads(read("royalcourt_events.json"))
    event = parse_event_match(events, "https://royalcourttheatre.com/events/man-to-man/")
    assert event is not None
    assert event["name"] == "Man to Man"

    instances = json.loads(read("royalcourt_man_to_man_instances.json"))
    result = parse_instances(event["name"], instances)
    assert result.title == "Man to Man"
    assert len(result.performances) > 10
    # dates sorted and ISO-ish
    assert result.performances[0].date_iso <= result.performances[-1].date_iso
    assert result.performances[0].date_iso.startswith("2026-")


def test_royalcourt_no_match_returns_none():
    events = json.loads(read("royalcourt_events.json"))
    assert parse_event_match(events, "https://royalcourttheatre.com/events/nope-xyz/") is None


# ----- National Theatre (JSON API) ---------------------------------------
def test_national_theatre_warhorse_all_available():
    event = json.loads(read("national_theatre_warhorse_api.json"))
    result = parse_event(event)
    assert result.title == "War Horse"
    assert len(result.performances) == 14
    # every War Horse performance is on sale ("auto")
    assert all(p.available for p in result.performances)
    p0 = result.performances[0]
    assert p0.price_text.startswith("£") and "–" in p0.price_text  # a range
    assert p0.book_url.startswith("https://tickets.nationaltheatre.org.uk/")
    # UTC 18:30Z shown in London local (BST, 7:30pm)
    assert "7:30pm" in p0.display_date


def test_national_theatre_status_marks_nonbookable_unavailable():
    event = json.loads(read("national_theatre_electra_api.json"))
    result = parse_event(event)
    assert "Electra" in result.title
    assert len(result.performances) == 57
    # exactly the one "nonbookable" instance is unavailable
    assert sum(1 for p in result.performances if not p.available) == 1
    assert sum(1 for p in result.performances if p.available) == 56


# ----- Almeida ------------------------------------------------------------
def test_almeida_production_title_and_soldout():
    title, sold_out = parse_production(read("almeida_golden_boy.html"))
    assert title == "Golden Boy"
    assert sold_out is True


def test_almeida_calendar_url_derivation():
    assert calendar_url("https://almeida.co.uk/whats-on/golden-boy/") == (
        "https://almeida.co.uk/calendar/?e=golden-boy"
    )


def test_almeida_parse_calendar_extracts_dates_and_availability():
    # Representative rendered-calendar text (the live calendar is JS-built).
    text = (
        "Wed 9 Sep 2026 7.30pm Sold Out . "
        "Thu 10 Sep 2026 7.30pm Book now £30 . "
        "Sat 12 Sep 2026 2.00pm Limited availability £45 ."
    )
    perfs = parse_calendar(text, "Golden Boy")
    assert len(perfs) == 3
    by_date = {p.date_iso[:10]: p for p in perfs}
    assert by_date["2026-09-09"].available is False
    assert by_date["2026-09-10"].available is True
    assert by_date["2026-09-10"].price_text == "£30"
    assert by_date["2026-09-12"].available is True

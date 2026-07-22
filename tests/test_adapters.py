"""Parser tests against real fixtures captured from the live sites.

Fixtures are real pages/responses captured from the theatres; the assertions
encode the user-confirmed ground truth for those captures.
"""
import json
import pathlib

from bot.adapters.almeida import parse_calendar, slug_from_url
from bot.adapters.national_theatre import perf_available_from_page
from bot.adapters.royal_court import (
    parse_event_match,
    parse_instances,
    parse_rendered_availability,
)
from bot.adapters.util import format_display_date, price_range

FIX = pathlib.Path(__file__).parent / "fixtures"


def read(name: str) -> str:
    return (FIX / name).read_text()


def load(name: str):
    return json.loads(read(name))


# ----- util ---------------------------------------------------------------
def test_format_display_date():
    assert format_display_date("2026-09-11T19:30:00") == "Fri 11 Sep 2026, 7:30pm"
    assert format_display_date("2026-09-12T14:00:00") == "Sat 12 Sep 2026, 2pm"


def test_price_range():
    assert price_range("from £30 up to £120") == "£30–£120"
    assert price_range("no prices here") == ""


# ----- Almeida (admin-ajax calendar) -------------------------------------
def test_almeida_slug_from_url():
    assert slug_from_url("https://almeida.co.uk/whats-on/golden-boy/") == "golden-boy"
    assert (
        slug_from_url("https://almeida.co.uk/calendar/?e=desire-under-the-elms")
        == "desire-under-the-elms"
    )


def test_almeida_golden_boy_sold_out():
    data = load("almeida_calendar_golden_boy.json")
    result = parse_calendar(data["instances"], "golden-boy")
    assert result.title == "Golden Boy"
    assert result.performances and not any(p.available for p in result.performances)


def test_almeida_desire_available():
    data = load("almeida_calendar_desire.json")
    result = parse_calendar(data["instances"], "desire-under-the-elms")
    assert "Desire" in result.title
    assert all(p.available for p in result.performances)  # every performance bookable


# ----- National Theatre (per-performance TNEW seat page) -----------------
def test_nt_perf_available_signal():
    assert perf_available_from_page(read("nt_perf_avail.html")) is True
    assert perf_available_from_page(read("nt_perf_sold.html")) is False
    assert perf_available_from_page("<html>a queue-it holding page</html>") is None


# ----- Royal Court (Spektrix schedule + rendered buyability) -------------
def test_royalcourt_event_match():
    events = load("royalcourt_events.json")
    ev = parse_event_match(events, "https://royalcourttheatre.com/events/man-to-man/")
    assert ev is not None and ev["name"] == "Man to Man"
    assert parse_event_match(events, "https://royalcourttheatre.com/events/nope/") is None


def test_royalcourt_blood_all_buyable():
    avail = parse_rendered_availability(read("royalcourt_blood_rendered.html"))
    assert len(avail) == 42 and all(avail.values())


def test_royalcourt_mantoman_excludes_access_only():
    avail = parse_rendered_availability(read("royalcourt_mantoman_rendered.html"))
    assert len(avail) == 55
    assert sum(avail.values()) == 35            # 20 "Sold out *" excluded
    assert avail["345967"] is False             # Thu 17 Sep 2:30pm = Access-only


def test_royalcourt_join_availability_by_instance_id():
    instances = load("royalcourt_man_to_man_instances.json")
    import re
    numeric = re.match(r"\d+", instances[0]["id"]).group(0)
    result = parse_instances("Man to Man", instances, {numeric: True})
    assert sum(1 for p in result.performances if p.available) == 1

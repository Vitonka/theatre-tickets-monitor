"""Parser tests against real fixtures captured from the live sites."""
import json
import pathlib

from bot.adapters.almeida import parse_calendar, slug_from_url
from bot.adapters.national_theatre import parse_event, parse_tnew_availability
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
    assert price_range("tickets from £30 up to £120 today") == "£30–£120"
    assert price_range("flat £45 seats") == "£45"
    assert price_range("no prices here") == ""


# ----- Royal Court (Spektrix) --------------------------------------------
def test_royalcourt_event_match_and_instances():
    events = load("royalcourt_events.json")
    event = parse_event_match(events, "https://royalcourttheatre.com/events/man-to-man/")
    assert event is not None and event["name"] == "Man to Man"

    instances = load("royalcourt_man_to_man_instances.json")
    result = parse_instances(event["name"], instances)
    assert result.title == "Man to Man"
    assert len(result.performances) > 10
    assert result.performances[0].date_iso <= result.performances[-1].date_iso


def test_royalcourt_no_match_returns_none():
    events = load("royalcourt_events.json")
    assert parse_event_match(events, "https://royalcourttheatre.com/events/nope-xyz/") is None


# ----- National Theatre (events API + TNEW real availability) ------------
def test_national_theatre_tnew_availability_parse():
    wh = parse_tnew_availability(read("national_theatre_warhorse_tnew.html"))
    cat = parse_tnew_availability(read("national_theatre_catarina_tnew.html"))
    assert wh and all(wh.values())          # War Horse: none sold out
    assert cat and not any(cat.values())    # Catarina: all sold out


def test_national_theatre_warhorse_available():
    event = load("national_theatre_warhorse_api.json")
    tnew = parse_tnew_availability(read("national_theatre_warhorse_tnew.html"))
    result = parse_event(event, tnew)
    assert result.title == "War Horse"
    assert len(result.performances) == 14
    assert all(p.available for p in result.performances)
    p0 = result.performances[0]
    assert p0.price_text.startswith("£") and "–" in p0.price_text
    assert p0.book_url.startswith("https://tickets.nationaltheatre.org.uk/")
    assert "7:30pm" in p0.display_date  # 18:30Z shown as London 7:30pm


def test_national_theatre_catarina_soldout_despite_onsale():
    # Every Catarina instance is bookingStatus="auto" (on sale) in the API,
    # yet the TNEW list marks them all sold out. The real signal must win.
    event = load("national_theatre_catarina_api.json")
    assert all(i["bookingStatus"] == "auto" for i in event["instances"][:1])
    tnew = parse_tnew_availability(read("national_theatre_catarina_tnew.html"))
    result = parse_event(event, tnew)
    assert "Catarina" in result.title
    assert not any(p.available for p in result.performances)


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
    assert len(result.performances) > 0
    assert not any(p.available for p in result.performances)


def test_almeida_desire_available():
    data = load("almeida_calendar_desire.json")
    result = parse_calendar(data["instances"], "desire-under-the-elms")
    assert "Desire" in result.title
    assert any(p.available for p in result.performances)


# ----- Royal Court rendered availability (real DOM) ----------------------
def test_royalcourt_rendered_all_bookable():
    avail = parse_rendered_availability(read("royalcourt_blood_rendered.html"))
    assert len(avail) == 42            # Blood of my Blood: 42 performances
    assert all(avail.values())         # all show a "Book now" action


def test_royalcourt_rendered_marks_soldout_unavailable():
    # A "Book now" instance is available; a "Sold out" / "Join the waiting
    # list" instance (still linking to /book/instance) is not.
    html = (
        '<li class="c-instance o-list__item"><time>Thu 1 Oct 7:45pm</time>'
        '<a href="/book/instance/111"><span class="o-button__text"><span>Book now</span></span></a></li>'
        '<li class="c-instance o-list__item"><time>Fri 2 Oct 7:45pm</time>'
        '<a href="/book/instance/222"><span class="o-button__text"><span>Join the waiting list</span></span></a></li>'
    )
    avail = parse_rendered_availability(html)
    assert avail == {"111": True, "222": False}


def test_royalcourt_join_availability_by_instance_id():
    instances = load("royalcourt_man_to_man_instances.json")
    # pretend the render said the first instance is bookable
    first_id = instances[0]["id"]
    import re as _re
    numeric = _re.match(r"\d+", first_id).group(0)
    result = parse_instances("Man to Man", instances, {numeric: True})
    avail = [p for p in result.performances if p.available]
    assert len(avail) == 1

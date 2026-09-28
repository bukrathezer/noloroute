import json
from datetime import date

from app.services.opening_hours import (
    MINUTES_PER_WEEK,
    google_weekday,
    hours_on,
    is_open_long_enough,
    open_minutes,
    parse_periods,
)

SUNDAY = date(2026, 10, 4)
MONDAY = date(2026, 10, 5)
TUESDAY = date(2026, 10, 6)
SATURDAY = date(2026, 10, 10)


def periods(*spans: tuple[int, str, int, str]) -> str:
    """JSON periods from (open_day, "HH:MM", close_day, "HH:MM") tuples; day 0 = Sunday."""
    out = []
    for open_day, open_at, close_day, close_at in spans:
        oh, om = map(int, open_at.split(":"))
        ch, cm = map(int, close_at.split(":"))
        out.append(
            {"open": {"day": open_day, "hour": oh, "minute": om}, "close": {"day": close_day, "hour": ch, "minute": cm}}
        )
    return json.dumps(out)


MUSEUM = periods(*[(d, "09:00", d, "18:00") for d in (0, 1, 3, 4, 5, 6)])  # closed on Tuesdays


def test_google_weekday_starts_on_sunday() -> None:
    assert google_weekday(SUNDAY) == 0
    assert google_weekday(MONDAY) == 1
    assert google_weekday(SATURDAY) == 6


def test_unknown_and_round_the_clock_hours() -> None:
    assert parse_periods(None) is None
    assert parse_periods("not json") is None
    always = json.dumps([{"open": {"day": 0, "hour": 0, "minute": 0}}])
    assert parse_periods(always) == [(0, MINUTES_PER_WEEK)]
    assert hours_on(always, TUESDAY) == "24/7"
    # Unknown hours count as open (parks and squares rarely list any).
    assert is_open_long_enough(None, TUESDAY, 60)


def test_regular_day_and_closed_day() -> None:
    assert hours_on(MUSEUM, MONDAY) == "09:00–18:00"
    assert hours_on(MUSEUM, TUESDAY) == "closed"
    assert open_minutes(parse_periods(MUSEUM), google_weekday(MONDAY)) == 9 * 60
    assert open_minutes(parse_periods(MUSEUM), google_weekday(TUESDAY)) == 0
    assert is_open_long_enough(MUSEUM, MONDAY, 120)
    assert not is_open_long_enough(MUSEUM, TUESDAY, 30)


def test_short_opening_fits_short_visits_only() -> None:
    brief = periods((1, "10:00", 1, "10:45"))
    assert is_open_long_enough(brief, MONDAY, 30)
    assert not is_open_long_enough(brief, MONDAY, 120)  # needs min(120, 90) open minutes


def test_only_the_sightseeing_window_counts() -> None:
    night = periods((1, "20:00", 1, "23:30"))
    assert open_minutes(parse_periods(night), google_weekday(MONDAY)) == 0  # after 20:00
    assert hours_on(night, MONDAY) == "20:00–23:30"


def test_period_past_midnight_and_past_saturday() -> None:
    bar = periods((6, "18:00", 0, "02:00"))  # Saturday 18:00 to Sunday 02:00 wraps the week
    assert hours_on(bar, SATURDAY) == "18:00–02:00"
    assert open_minutes(parse_periods(bar), google_weekday(SATURDAY)) == 2 * 60  # 18:00-20:00
    assert hours_on(bar, SUNDAY) == "closed"  # opens on Saturday, not Sunday


def test_several_periods_in_a_day() -> None:
    lunch_break = periods((1, "09:00", 1, "12:00"), (1, "14:00", 1, "18:00"))
    assert hours_on(lunch_break, MONDAY) == "09:00–12:00, 14:00–18:00"
    assert open_minutes(parse_periods(lunch_break), google_weekday(MONDAY)) == 7 * 60

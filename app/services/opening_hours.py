"""Opening hours in Google Places' "periods" format, as stored in POI.opening_hours (JSON).

Each period is {"open": {"day", "hour", "minute"}, "close": {...}} with day 0 = Sunday. A single
period without "close" means open 24/7. Times are laid out on one week-long line of minutes
(Sunday 00:00 = 0 ... Saturday 23:59 = 10079), so periods that run past midnight or past
Saturday night need no special cases beyond shifting by a week.
"""

import json
from datetime import date

MINUTES_PER_DAY = 24 * 60
MINUTES_PER_WEEK = 7 * MINUTES_PER_DAY
SIGHTSEEING_WINDOW = (9 * 60, 20 * 60)  # the part of a day a plan uses: 09:00-20:00

Interval = tuple[int, int]  # (start, end) in week minutes, end exclusive


def google_weekday(day: date) -> int:
    """Google's day number for a date: 0 = Sunday ... 6 = Saturday."""
    return (day.weekday() + 1) % 7


def parse_periods(raw: str | None) -> list[Interval] | None:
    """Week-minute intervals, [(0, MINUTES_PER_WEEK)] for 24/7, or None when hours are unknown."""
    if not raw:
        return None
    try:
        periods = json.loads(raw)
    except ValueError:
        return None
    intervals: list[Interval] = []
    for period in periods:
        start = _week_minute(period["open"])
        if "close" not in period:
            return [(0, MINUTES_PER_WEEK)]
        end = _week_minute(period["close"])
        if end <= start:  # runs past Saturday midnight
            end += MINUTES_PER_WEEK
        intervals.append((start, end))
    return intervals


def open_minutes(intervals: list[Interval] | None, weekday: int, window: Interval = SIGHTSEEING_WINDOW) -> int:
    """How many minutes of `window` (minutes within the day) the place is open on `weekday`.

    Unknown hours count as open all day: parks, streets and squares usually have none.
    """
    if intervals is None:
        return window[1] - window[0]
    day_start = weekday * MINUTES_PER_DAY
    lo, hi = day_start + window[0], day_start + window[1]
    total = 0
    for start, end in intervals:
        # A period can also reach this day from the previous week (e.g. Saturday night into Sunday).
        for shift in (-MINUTES_PER_WEEK, 0, MINUTES_PER_WEEK):
            total += max(0, min(end + shift, hi) - max(start + shift, lo))
    return min(total, hi - lo)


def is_open_long_enough(raw: str | None, on: date, visit_minutes: int) -> bool:
    """Whether a visit fits into the place's hours on that date (capped at 90 open minutes)."""
    needed = min(visit_minutes, 90)
    return open_minutes(parse_periods(raw), google_weekday(on)) >= needed


def hours_on(raw: str | None, on: date) -> str | None:
    """Human-readable hours for that date, e.g. "09:00–18:00", "24/7", "closed"; None if unknown."""
    intervals = parse_periods(raw)
    if intervals is None:
        return None
    if intervals == [(0, MINUTES_PER_WEEK)]:
        return "24/7"
    day_start = google_weekday(on) * MINUTES_PER_DAY
    parts = []
    for start, end in sorted(intervals):
        for shift in (-MINUTES_PER_WEEK, 0, MINUTES_PER_WEEK):
            s, e = start + shift, end + shift
            if day_start <= s < day_start + MINUTES_PER_DAY:  # opens on this day
                parts.append(f"{_clock(s - day_start)}–{_clock(e - day_start)}")
    return ", ".join(parts) if parts else "closed"


def _week_minute(point: dict[str, int]) -> int:
    return point["day"] * MINUTES_PER_DAY + point.get("hour", 0) * 60 + point.get("minute", 0)


def _clock(minutes_from_midnight: int) -> str:
    # Closing times past midnight show as 01:00 rather than 25:00.
    minutes = minutes_from_midnight % MINUTES_PER_DAY
    return f"{minutes // 60:02d}:{minutes % 60:02d}"

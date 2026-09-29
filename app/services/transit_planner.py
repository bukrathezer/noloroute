"""Transit mode: each leg of a day is walked or taken by public transport, whichever is better.

1. Two Route Matrix calls give walking and transit times between every pair of points (the
   hotel and the day's stops), with transit timetables for that day at midday.
2. choose_leg picks walking or transit for every pair. Short walks are always walked, and
   transit has to save a few minutes to be worth the waiting, stairs and tickets.
3. Google can't optimize the order of transit waypoints, so our own TSP solver (tsp.py) orders
   the stops on the chosen times.
4. Each leg of the final order is routed once more in its chosen mode, departing when the
   traveller would actually leave (09:00 plus the travel and visits before it). That gives the
   street path, the lines to take and the time for that exact departure.

Without transit data (Google has none for many smaller cities) every leg is simply walked.
"""

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
from itertools import pairwise

from app.services.geo import DETOUR_FACTOR, LatLng, haversine_km
from app.services.routes_client import Leg, LoopRoute, MatrixCell, RoutesAPIError, RoutesClient, TravelMode
from app.services.tsp import shortest_loop

logger = logging.getLogger(__name__)

WALK_ALWAYS_SECONDS = 10 * 60  # walks this short are never swapped for transit
TRANSIT_MIN_SAVING_SECONDS = 5 * 60  # transit must beat walking by this much to be chosen
ALTERNATIVE_MIN_SAVING_SECONDS = 3 * 60  # a quicker option not taken is mentioned from this saving on
DAY_START = time(9, 0)  # when the traveller leaves the hotel
MATRIX_DEPARTURE = time(12, 0)  # midday: typical daytime service, used to compare and order
# Timetables are published only a few weeks ahead. For later dates, the same weekday in the
# coming week is used instead: most services repeat weekly.
TIMETABLE_HORIZON_DAYS = 28
WALK_SPEED_KMH = 4.5  # for a pair Google has no route for at all


@dataclass(frozen=True)
class LegChoice:
    mode: TravelMode
    seconds: int
    meters: int
    alternative: tuple[TravelMode, int] | None  # the option not taken, if it's worth showing
    cost: float  # what the ordering minimizes: the time, plus the penalty for transit
    routed: bool = True  # False: Google found no route, so this is a straight-line estimate


def choose_leg(walk: MatrixCell | None, transit: MatrixCell | None) -> LegChoice | None:
    """Walk or ride from A to B? None when Google knows no route either way."""
    if walk and (
        transit is None
        or walk.seconds <= WALK_ALWAYS_SECONDS
        or walk.seconds - transit.seconds < TRANSIT_MIN_SAVING_SECONDS
    ):
        # Only mention transit when it would have been noticeably quicker.
        worth_mentioning = transit and walk.seconds - transit.seconds >= ALTERNATIVE_MIN_SAVING_SECONDS
        faster = (TravelMode.TRANSIT, transit.seconds) if transit and worth_mentioning else None
        return LegChoice(TravelMode.WALK, walk.seconds, walk.meters, faster, cost=walk.seconds)
    if transit:
        on_foot = (TravelMode.WALK, walk.seconds) if walk else None
        cost = transit.seconds + TRANSIT_MIN_SAVING_SECONDS
        return LegChoice(TravelMode.TRANSIT, transit.seconds, transit.meters, on_foot, cost=cost)
    return None


def timetable_day(day: date | None, today: date) -> date:
    """The date whose timetable to use: the trip day itself, or tomorrow for plans without dates."""
    if day is None:
        return today + timedelta(days=1)
    days_ahead = (day - today).days
    if days_ahead > TIMETABLE_HORIZON_DAYS:
        day -= timedelta(weeks=(days_ahead - 1) // 7)  # lands 1..7 days from today, same weekday
    return day


async def order_day_transit(
    hotel: LatLng,
    stops: Sequence[LatLng],
    visit_minutes: Sequence[int],
    client: RoutesClient,
    day: date | None,
    tz: tzinfo,
) -> tuple[LoopRoute, bool]:
    """Order a day and route its legs. Also returns whether Google had any transit route here.

    Raises RoutesAPIError when the matrices can't be fetched; the caller falls back to estimates.
    """
    points = [hotel, *stops]
    service_day = timetable_day(day, datetime.now(tz).date())
    walk, transit = await asyncio.gather(
        client.compute_matrix(points, TravelMode.WALK),
        client.compute_matrix(points, TravelMode.TRANSIT, departure=_at(service_day, MATRIX_DEPARTURE, tz)),
    )
    transit_available = any(cell for i, row in enumerate(transit) for j, cell in enumerate(row) if i != j)

    n = len(points)
    choices = [
        [choose_leg(walk[i][j], transit[i][j]) or _straight_walk(points[i], points[j]) for j in range(n)]
        for i in range(n)
    ]
    order = shortest_loop([[choice.cost for choice in row] for row in choices])  # points 1..n-1
    path = list(pairwise([0, *order, 0]))

    # When each leg starts: leave the hotel at DAY_START, then travel and visit in turn.
    departures: list[datetime] = []
    clock = _at(service_day, DAY_START, tz)
    for a, b in path:
        departures.append(clock)
        clock += timedelta(seconds=choices[a][b].seconds)
        if b != 0:
            clock += timedelta(minutes=visit_minutes[b - 1])

    legs = await asyncio.gather(
        *(
            _route_leg(client, points[a], points[b], choices[a][b], departure)
            for (a, b), departure in zip(path, departures, strict=True)
        )
    )
    return LoopRoute(order=[i - 1 for i in order], legs=list(legs)), transit_available


async def _route_leg(client: RoutesClient, a: LatLng, b: LatLng, choice: LegChoice, departure: datetime) -> Leg:
    """The chosen leg with its path and rides; the matrix numbers (without a path) if that fails."""
    fallback = Leg(
        choice.seconds,
        choice.meters,
        mode=choice.mode,
        walk_seconds=choice.seconds if choice.mode is TravelMode.WALK else None,
        alternative=choice.alternative,
    )
    if not choice.routed:
        return fallback
    try:
        leg = await client.route_leg(a, b, choice.mode, departure=departure)
    except RoutesAPIError as exc:
        logger.warning("Leg routing failed, using matrix times: %s", exc)
        return fallback
    # At the exact departure time Google may find that walking is best after all: then the
    # leg is a walk, and the alternative we had in mind no longer applies.
    alternative = choice.alternative if leg.mode is choice.mode else None
    return Leg(leg.seconds, leg.meters, leg.polyline, leg.mode, leg.rides, leg.walk_seconds, alternative)


def _straight_walk(a: LatLng, b: LatLng) -> LegChoice:
    """A straight-line walking estimate, for a pair Google has no route for."""
    km = haversine_km(a, b) * DETOUR_FACTOR
    seconds = round(km / WALK_SPEED_KMH * 3600)
    return LegChoice(TravelMode.WALK, seconds, round(km * 1000), None, cost=seconds, routed=False)


def _at(day: date, clock: time, tz: tzinfo) -> datetime:
    return datetime.combine(day, clock, tzinfo=tz)

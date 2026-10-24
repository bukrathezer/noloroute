"""Transit mode: each leg of a day is walked or taken by public transport, whichever is better.

1. Two Route Matrix calls give walking and transit times between every pair of points (the
   hotel and the day's stops), with transit timetables for that day at midday.
2. choose_leg picks walking or transit for every pair. Short walks are always walked, and
   transit has to save a few minutes to be worth the waiting, stairs and tickets.
3. Google can't optimize the order of transit waypoints, so our own TSP solver (tsp.py) orders
   the stops on the chosen times. If the day runs too long, its least valuable stop is dropped
   and the rest re-ordered; the matrices already cover every pair, so this costs no API calls.
4. Each leg of the final order is routed once more in its chosen mode, departing when the
   traveller would actually leave (09:00 plus the travel and visits before it). That gives the
   street path, the lines to take and the time for that exact departure.

Without any transit data for the place (Google gives none for Japan to apps like this one), long
legs would all be walked: days of 5 km walks that lose their stops. Instead, rides are estimated
from the distance (estimated_transit), short legs are still walked on Google's real times, and the
estimated rides are marked as such, without lines.
"""

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
from itertools import pairwise

from app.services.geo import DETOUR_FACTOR, LatLng, haversine_km
from app.services.routes_client import Leg, LoopRoute, Matrix, MatrixCell, RoutesAPIError, RoutesClient, TravelMode
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
# An estimated ride (see estimated_transit): walking to and from the stations and waiting, plus the
# distance at a typical big-city metro speed, stops and changes included.
ESTIMATED_RIDE_OVERHEAD_SECONDS = 10 * 60
ESTIMATED_RIDE_KMH = 22.0
# Countries Google gives no transit routes for (checked for every city in October 2026). Their
# transit matrix would come back empty, using up the daily Routes quota for nothing.
NO_TRANSIT_DATA_COUNTRIES = frozenset({"JP"})


def has_transit_data(country_code: str | None) -> bool:
    """Whether to ask Google for transit routes in a country (see NO_TRANSIT_DATA_COUNTRIES)."""
    return (country_code or "") not in NO_TRANSIT_DATA_COUNTRIES


@dataclass(frozen=True)
class LegChoice:
    mode: TravelMode
    seconds: int
    meters: int
    alternative: tuple[TravelMode, int] | None  # the option not taken, if it's worth showing
    cost: float  # what the ordering minimizes: the time, plus the penalty for transit
    routed: bool = True  # False: Google found no route, so this is a straight-line estimate
    estimated: bool = False  # an estimated ride: no Google transit data here


def choose_leg(walk: MatrixCell | None, transit: MatrixCell | None) -> LegChoice | None:
    """Walk or ride from A to B? None when Google knows no route either way."""
    if walk and (
        transit is None
        or walk.seconds <= WALK_ALWAYS_SECONDS
        or walk.seconds - transit.seconds < TRANSIT_MIN_SAVING_SECONDS
    ):
        # Only mention transit when it would have been noticeably quicker (and known, not guessed).
        worth_mentioning = (
            transit and not transit.estimated and walk.seconds - transit.seconds >= ALTERNATIVE_MIN_SAVING_SECONDS
        )
        faster = (TravelMode.TRANSIT, transit.seconds) if transit and worth_mentioning else None
        return LegChoice(TravelMode.WALK, walk.seconds, walk.meters, faster, cost=walk.seconds)
    if transit:
        on_foot = (TravelMode.WALK, walk.seconds) if walk else None
        cost = transit.seconds + TRANSIT_MIN_SAVING_SECONDS
        return LegChoice(
            TravelMode.TRANSIT,
            transit.seconds,
            transit.meters,
            on_foot,
            cost=cost,
            routed=not transit.estimated,  # Google has no ride to route
            estimated=transit.estimated,
        )
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
    values: Sequence[float] | None = None,
    max_minutes: int | None = None,
    transit_data: bool = True,
) -> tuple[LoopRoute, bool]:
    """Order a day and route its legs. Also returns whether Google had any transit route here.

    `transit_data` False: Google is known to have no transit routes for the place, so only the
    walking matrix is fetched and rides are estimated right away.

    While the day (visits plus travel) runs over `max_minutes`, the stop with the lowest value
    in `values` is dropped: it is left out of the returned order.

    Raises RoutesAPIError when the matrices can't be fetched; the caller falls back to estimates.
    """
    points = [hotel, *stops]
    service_day = timetable_day(day, datetime.now(tz).date())
    if transit_data:
        walk, transit = await asyncio.gather(
            client.compute_matrix(points, TravelMode.WALK),
            client.compute_matrix(points, TravelMode.TRANSIT, departure=_at(service_day, MATRIX_DEPARTURE, tz)),
        )
    else:
        walk, transit = await client.compute_matrix(points, TravelMode.WALK), []
    transit_available = any(cell for i, row in enumerate(transit) for j, cell in enumerate(row) if i != j)
    if not transit_available:
        transit = estimated_transit(points, walk)

    n = len(points)
    choices = [
        [choose_leg(walk[i][j], transit[i][j]) or _straight_walk(points[i], points[j]) for j in range(n)]
        for i in range(n)
    ]
    kept = list(range(1, n))  # point indexes of the stops still in the day
    while True:
        order = _best_order(choices, kept)
        path = list(pairwise([0, *order, 0]))
        minutes = sum(choices[a][b].seconds for a, b in path) / 60 + sum(visit_minutes[k - 1] for k in kept)
        if max_minutes is None or values is None or minutes <= max_minutes or len(kept) == 1:
            break
        kept.remove(min(kept, key=lambda k: values[k - 1]))

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
            _route_leg(client, points[a], points[b], choices[a][b], departure, transit_available)
            for (a, b), departure in zip(path, departures, strict=True)
        )
    )
    return LoopRoute(order=[i - 1 for i in order], legs=list(legs)), transit_available


async def _route_leg(
    client: RoutesClient, a: LatLng, b: LatLng, choice: LegChoice, departure: datetime, has_transit: bool = True
) -> Leg:
    """The chosen leg with its path and rides; the matrix numbers (without a path) if that fails.

    A walk that turns out to take a ferry (Google's walks do where there is no other way, as to
    Venice's islands) is a ride in fact: it is routed as transit, so the boat's line is shown.
    Where Google has no transit route, it stays a walk, marked as taking a ferry.
    """
    fallback = Leg(
        choice.seconds,
        choice.meters,
        mode=choice.mode,
        walk_seconds=choice.seconds if choice.mode is TravelMode.WALK else None,
        alternative=choice.alternative,
        estimated=choice.estimated,
    )
    if not choice.routed:
        return fallback
    try:
        leg = await client.route_leg(a, b, choice.mode, departure=departure)
    except RoutesAPIError as exc:
        logger.warning("Leg routing failed, using matrix times: %s", exc)
        return fallback
    # (Not when transit was asked for already: Google found a walk best then.)
    if choice.mode is TravelMode.WALK and leg.mode is TravelMode.WALK and leg.ferry and has_transit:
        try:
            ride = await client.route_leg(a, b, TravelMode.TRANSIT, departure=departure)
        except RoutesAPIError:
            ride = None
        if ride is not None and ride.mode is TravelMode.TRANSIT:
            return Leg(ride.seconds, ride.meters, ride.polyline, ride.mode, ride.rides, ride.walk_seconds)
    # At the exact departure time Google may find that walking is best after all: then the
    # leg is a walk, and the alternative we had in mind no longer applies.
    alternative = choice.alternative if leg.mode is choice.mode else None
    return Leg(
        leg.seconds, leg.meters, leg.polyline, leg.mode, leg.rides, leg.walk_seconds, alternative, ferry=leg.ferry
    )


def estimated_transit(points: Sequence[LatLng], walk: Matrix) -> Matrix:
    """Estimated ride times between every pair, for a place without any Google transit data.

    A ride takes ESTIMATED_RIDE_OVERHEAD_SECONDS (to and from the stations, waiting) plus the
    distance (the walking route's, else the straight line's with a detour) at ESTIMATED_RIDE_KMH.
    Only legs where that clearly beats walking become rides (choose_leg): 2 km and more, roughly.
    """
    n = len(points)
    matrix: Matrix = []
    for i in range(n):
        row: list[MatrixCell | None] = []
        for j in range(n):
            if i == j:
                row.append(None)
                continue
            on_foot = walk[i][j]
            meters = on_foot.meters if on_foot else round(haversine_km(points[i], points[j]) * DETOUR_FACTOR * 1000)
            seconds = ESTIMATED_RIDE_OVERHEAD_SECONDS + round(meters / 1000 / ESTIMATED_RIDE_KMH * 3600)
            if on_foot is None:
                # No walking route to compare with in choose_leg: ride only where it clearly beats
                # the straight-line walk used for such pairs, else leave the pair to that walk.
                straight = _straight_walk(points[i], points[j]).seconds
                if straight <= WALK_ALWAYS_SECONDS or straight - seconds < TRANSIT_MIN_SAVING_SECONDS:
                    row.append(None)
                    continue
            row.append(MatrixCell(seconds, meters, estimated=True))
        matrix.append(row)
    return matrix


def _best_order(choices: list[list[LegChoice]], kept: list[int]) -> list[int]:
    """The best visiting order of the `kept` points (hotel = 0), as point indexes."""
    points = [0, *kept]
    order = shortest_loop([[choices[a][b].cost for b in points] for a in points])
    return [points[i] for i in order]


def _straight_walk(a: LatLng, b: LatLng) -> LegChoice:
    """A straight-line walking estimate, for a pair Google has no route for."""
    km = haversine_km(a, b) * DETOUR_FACTOR
    seconds = round(km / WALK_SPEED_KMH * 3600)
    return LegChoice(TravelMode.WALK, seconds, round(km * 1000), None, cost=seconds, routed=False)


def _at(day: date, clock: time, tz: tzinfo) -> datetime:
    return datetime.combine(day, clock, tzinfo=tz)

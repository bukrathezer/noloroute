"""Trip planning: choose which POIs to visit, split them into days, and order each day.

1. select_stops     Score every POI (popularity, discounted by distance from the hotel) and
                    repeatedly take the best one that still fits the trip's time and budget. Each
                    pick lowers the score of its category, so the trip stays varied.
2. split_into_days  "Route first, split second": one round trip through all chosen stops (our TSP
                    solver on straight-line distances), cut into `days` consecutive stretches of
                    roughly equal time. Neighbouring sights sit next to each other on the round
                    trip, so they stay on the same day; of all places to start cutting, the one
                    with the least total distance wins.
3. fit_to_dates     With trip dates: a stop that is closed on its day moves to the least busy day
                    it is open on (or is dropped); on rainy days, outdoor stops move to a dry day.
4. order_day        Walking and driving: Google Routes API optimizes the visiting order (hotel ->
                    stops -> hotel) and returns real travel times. Transit: each leg is walked or
                    ridden, and our own TSP solver orders the day (see transit_planner.py). If
                    Google fails, fall back to nearest-neighbour ordering with straight-line time
                    estimates so a plan is always returned. A day that still runs well over 8 hours
                    with real travel times loses its least popular stops.
"""

import asyncio
import logging
import math
import re
import unicodedata
from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, tzinfo
from decimal import Decimal
from itertools import pairwise
from typing import Literal

from app.models import POI
from app.schemas.route import DayPlan, DayWeatherOut, LegDetails, PlannedStop, TransitRideOut
from app.services.geo import DETOUR_FACTOR, LatLng, haversine_km
from app.services.opening_hours import hours_on, is_open_long_enough
from app.services.routes_client import Leg, LoopRoute, RoutesAPIError, RoutesClient, TravelMode
from app.services.transit_planner import order_day_transit
from app.services.tsp import shortest_loop
from app.services.weather import DayWeather

logger = logging.getLogger(__name__)

DAY_MINUTES = 8 * 60  # sightseeing time per day, travel included
MAX_DAY_MINUTES = DAY_MINUTES + 30  # with real travel times a day may run a little over, not more
MAX_TRIMS_PER_DAY = 3  # dropping a stop re-routes the day: one more Google request each time
CATEGORY_REPEAT_DECAY = 0.75  # each pick from a category scales that category's scores by this
CURATED_POPULARITY_PERCENTILE = 0.95  # hand-entered POIs have no Google rating: treat as top 5%
MAX_HOTEL_DISTANCE_KM = 25.0  # from the nearest POI; beyond this the hotel isn't in the city

# Google sometimes lists one sight twice (e.g. "Louvre Museum" and "Louvre Pyramid"). Two POIs
# are treated as the same sight if they are this close and share a distinctive name word.
NEAR_DUPLICATE_KM = 0.25
GENERIC_NAME_WORDS = {
    "museum", "musee", "muzesi", "park", "parc", "parki", "garden", "gardens", "jardin", "jardins",
    "mosque", "camii", "church", "eglise", "basilica", "basilique", "cathedral", "cathedrale",
    "chapel", "chapelle", "palace", "palais", "square", "place", "meydani", "tower", "tour",
    "kulesi", "market", "marche", "bazaar", "carsisi", "grand", "grande", "great", "saint",
    "sainte", "notre", "dame", "paris", "istanbul", "national", "house", "hall",
}  # fmt: skip


@dataclass(frozen=True)
class ModeProfile:
    travel_min_per_stop: int  # travel allowance per stop while selecting; real times come from routing
    distance_half_score_km: float  # a POI this far from the hotel scores half as much as one next door
    fallback_speed_kmh: float  # average speed for straight-line estimates when Google is unavailable


MODE_PROFILES = {
    TravelMode.DRIVE: ModeProfile(travel_min_per_stop=20, distance_half_score_km=10.0, fallback_speed_kmh=18.0),
    TravelMode.WALK: ModeProfile(travel_min_per_stop=30, distance_half_score_km=4.0, fallback_speed_kmh=4.5),
    # Door to door, waiting included; short hops are walked, longer ones ridden.
    TravelMode.TRANSIT: ModeProfile(travel_min_per_stop=25, distance_half_score_km=7.0, fallback_speed_kmh=12.0),
}

RoutingSource = Literal["google", "estimate"]

# Categories that are no fun in the rain: avoided on rainy days when a dry day is available.
OUTDOOR_CATEGORIES = {"PARK", "VIEWPOINT"}
RAIN_OUTDOOR_PENALTY = 0.5  # outdoor scores shrink by up to this much as the share of rainy days grows


class HotelTooFarError(ValueError):
    pass


@dataclass(frozen=True)
class RoutedDay:
    """A routed day. Stops missing from loop.order were dropped to keep the day short enough."""

    loop: LoopRoute
    source: RoutingSource
    transit_available: bool | None = None  # transit plans only: whether Google had any transit route


async def plan_trip(
    pois: Sequence[POI],
    hotel: LatLng,
    days: int,
    budget: Decimal | None,
    mode: TravelMode,
    routes_client: RoutesClient | None,
    dates: Sequence[date] | None = None,
    weather: Sequence[DayWeather] | None = None,
    tz: tzinfo = UTC,
) -> list[DayPlan]:
    """Plan the trip. `dates` (one per day) enables opening hours; `weather` (one per day) rain tweaks.

    `tz` is the city's time zone, which transit timetables are read in.
    """
    if not pois or min(haversine_km(hotel, location(p)) for p in pois) > MAX_HOTEL_DISTANCE_KM:
        raise HotelTooFarError(f"Accommodation is more than {MAX_HOTEL_DISTANCE_KM:g} km from every sight")

    rainy = [w.is_rainy for w in weather] if weather else [False] * days
    if dates:
        # A place that is closed on every day of the trip cannot be visited at all.
        pois = [p for p in pois if any(is_open_long_enough(p.opening_hours, d, p.avg_duration_min) for d in dates)]

    chosen = select_stops(pois, hotel, days, budget, mode, rainy_share=sum(rainy) / days)
    groups = split_into_days(chosen, hotel, days, mode)
    rain_adjusted = [False] * days
    if dates:
        groups, rain_adjusted = fit_to_dates(groups, dates, rainy, mode)

    # Days are independent, so route them concurrently.
    routed = await asyncio.gather(
        *(
            order_day(hotel, group, mode, routes_client, day=dates[i] if dates else None, tz=tz)
            for i, group in enumerate(groups)
        )
    )
    return [
        build_day(
            day_number,
            group,
            day_route,
            day_date=dates[day_number - 1] if dates else None,
            weather=to_weather_out(weather[day_number - 1]) if weather else None,
            rain_adjusted=rain_adjusted[day_number - 1],
        )
        for day_number, (group, day_route) in enumerate(zip(groups, routed, strict=True), start=1)
    ]


def to_weather_out(weather: DayWeather) -> DayWeatherOut:
    return DayWeatherOut(
        source=weather.source,
        condition=weather.condition,
        temp_max_c=weather.temp_max_c,
        temp_min_c=weather.temp_min_c,
        precipitation_chance=weather.precipitation_chance,
        is_rainy=weather.is_rainy,
    )


def location(poi: POI) -> LatLng:
    return LatLng(poi.latitude, poi.longitude)


def popularity(poi: POI) -> float | None:
    """rating x log10(reviews)^2: grows with review count, with diminishing returns."""
    if poi.rating is None or not poi.user_rating_count:
        return None
    return poi.rating * math.log10(1 + poi.user_rating_count) ** 2


def stop_minutes(poi: POI, mode: TravelMode) -> int:
    return poi.avg_duration_min + MODE_PROFILES[mode].travel_min_per_stop


def select_stops(
    pois: Sequence[POI],
    hotel: LatLng,
    days: int,
    budget: Decimal | None,
    mode: TravelMode,
    rainy_share: float = 0.0,
) -> list[POI]:
    """Greedy: repeatedly take the highest (category-adjusted) score that still fits."""
    half_score_km = MODE_PROFILES[mode].distance_half_score_km
    known = sorted(p for p in map(popularity, pois) if p is not None)
    curated_popularity = known[int(CURATED_POPULARITY_PERCENTILE * (len(known) - 1))] if known else 1.0
    # The rainier the trip, the less parks and viewpoints are worth.
    outdoor_factor = 1 - RAIN_OUTDOOR_PENALTY * rainy_share

    def base_score(poi: POI) -> float:
        pop = popularity(poi) or curated_popularity
        score = pop / (1 + haversine_km(hotel, location(poi)) / half_score_km)
        return score * outdoor_factor if poi.category in OUTDOOR_CATEGORIES else score

    scores = {poi.id: base_score(poi) for poi in pois}
    capacity = days * DAY_MINUTES
    chosen: list[POI] = []
    used_minutes = 0
    spent = Decimal(0)
    per_category: Counter[str] = Counter()

    def fits(poi: POI) -> bool:
        if used_minutes + stop_minutes(poi, mode) > capacity:
            return False
        # Unknown prices are treated as free; the response reports how many stops were unpriced.
        if budget is not None and poi.entry_price is not None and spent + poi.entry_price > budget:
            return False
        # Earlier picks were already checked in earlier rounds; only the newest one is new.
        return not (chosen and is_near_duplicate(poi, chosen[-1:]))

    candidates = list(pois)
    while True:
        # Time and money only get used up, and picks only accumulate, so a POI that doesn't fit
        # now never will.
        candidates = [poi for poi in candidates if fits(poi)]
        if not candidates:
            return chosen
        best = max(candidates, key=lambda p: scores[p.id] * CATEGORY_REPEAT_DECAY ** per_category[p.category])
        candidates.remove(best)
        chosen.append(best)
        used_minutes += stop_minutes(best, mode)
        per_category[best.category] += 1
        if best.entry_price is not None:
            spent += best.entry_price


def is_near_duplicate(poi: POI, chosen: Sequence[POI]) -> bool:
    words = _distinctive_words(poi.name)
    return any(
        haversine_km(location(poi), location(other)) < NEAR_DUPLICATE_KM and words & _distinctive_words(other.name)
        for other in chosen
    )


def _distinctive_words(name: str) -> set[str]:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return {w for w in re.findall(r"[a-z]+", ascii_name) if len(w) >= 4 and w not in GENERIC_NAME_WORDS}


def split_into_days(stops: Sequence[POI], hotel: LatLng, days: int, mode: TravelMode) -> list[list[POI]]:
    """Route first, split second: cut one round trip through all stops into `days` stretches."""
    if len(stops) <= days:
        return [[stop] for stop in stops] + [[] for _ in range(days - len(stops))]
    points = [hotel, *(location(s) for s in stops)]
    km = [[haversine_km(a, b) for b in points] for a in points]
    index = {stop.id: i for i, stop in enumerate(stops, start=1)}  # position in `points`
    tour = [stops[i - 1] for i in shortest_loop(km)]

    def day_km(group: list[POI]) -> float:
        path = [0, *(index[stop.id] for stop in group), 0]
        return sum(km[a][b] for a, b in pairwise(path))

    # The round trip is a circle: try every stop as the start of day 1.
    candidates = (_cut_evenly(tour[start:] + tour[:start], days, mode) for start in range(len(tour)))
    return min(candidates, key=lambda groups: sum(day_km(g) for g in groups))


def _cut_evenly(sequence: Sequence[POI], days: int, mode: TravelMode) -> list[list[POI]]:
    """Cut the sequence into `days` consecutive groups of roughly equal time."""
    remaining_minutes = sum(stop_minutes(s, mode) for s in sequence)
    groups: list[list[POI]] = []
    current: list[POI] = []
    current_minutes = 0

    for i, stop in enumerate(sequence):
        minutes = stop_minutes(stop, mode)
        days_left = days - len(groups)  # including the current day
        stops_left = len(sequence) - i  # including this stop
        target = (current_minutes + remaining_minutes) / days_left
        # Close the day if this stop would push it past its fair share (by more than half the
        # stop), or if every later day still needs at least one stop.
        full = current_minutes + minutes / 2 > target
        if current and days_left > 1 and (full or stops_left < days_left):
            groups.append(current)
            current, current_minutes = [], 0
        current.append(stop)
        current_minutes += minutes
        remaining_minutes -= minutes

    groups.append(current)
    return groups + [[] for _ in range(days - len(groups))]


def fit_to_dates(
    groups: list[list[POI]], dates: Sequence[date], rainy: Sequence[bool], mode: TravelMode
) -> tuple[list[list[POI]], list[bool]]:
    """Make each day's stops fit its date: move stops off days they are closed on, and outdoor
    stops off rainy days, to the least busy day that suits them.

    Returns the new groups and, per day, whether outdoor stops were moved away because of rain.
    """
    groups = [list(g) for g in groups]
    load = [sum(stop_minutes(s, mode) for s in g) for g in groups]
    rain_adjusted = [False] * len(groups)

    def open_on(poi: POI, day: int) -> bool:
        return is_open_long_enough(poi.opening_hours, dates[day], poi.avg_duration_min)

    def move(poi: POI, src: int, candidates: list[int]) -> bool:
        if not candidates:
            return False
        dst = min(candidates, key=lambda d: (load[d], abs(d - src)))  # least busy, then nearest
        groups[src].remove(poi)
        groups[dst].append(poi)
        load[src] -= stop_minutes(poi, mode)
        load[dst] += stop_minutes(poi, mode)
        return True

    days = range(len(groups))
    # 1. Closed that day: move to a day it is open on, or drop it.
    for day in days:
        for poi in [p for p in groups[day] if not open_on(p, day)]:
            if not move(poi, day, [d for d in days if d != day and open_on(poi, d)]):
                groups[day].remove(poi)
                load[day] -= stop_minutes(poi, mode)
    # 2. Rain: move outdoor stops to a dry day they are open on; keep them if there is none.
    for day in days:
        if not rainy[day]:
            continue
        for poi in [p for p in groups[day] if p.category in OUTDOOR_CATEGORIES]:
            if move(poi, day, [d for d in days if not rainy[d] and open_on(poi, d)]):
                rain_adjusted[day] = True
    return groups, rain_adjusted


async def order_day(
    hotel: LatLng,
    stops: Sequence[POI],
    mode: TravelMode,
    routes_client: RoutesClient | None,
    day: date | None = None,
    tz: tzinfo = UTC,
    max_minutes: int | None = MAX_DAY_MINUTES,
) -> RoutedDay:
    """Order one day's stops and route its legs. `day` and `tz` pick the transit timetable.

    If the day runs over `max_minutes` (visits plus real travel), its least popular stops are
    dropped until it fits.
    """
    if not stops:
        return RoutedDay(LoopRoute(order=[], legs=[Leg(seconds=0, meters=0)]), "estimate")
    points = [location(s) for s in stops]
    if routes_client is not None:
        try:
            if mode is TravelMode.TRANSIT:
                # The transit planner trims with its travel-time matrices, at no extra cost.
                visits = [s.avg_duration_min for s in stops]
                values = [trim_value(s) for s in stops]
                loop, has_transit = await order_day_transit(
                    hotel, points, visits, routes_client, day, tz, values=values, max_minutes=max_minutes
                )
                return RoutedDay(loop, "google", transit_available=has_transit)

            async def optimize(kept: list[int]) -> LoopRoute:
                return await routes_client.optimize_loop(hotel, [points[i] for i in kept], mode)

            return RoutedDay(await route_trimmed(stops, optimize, max_minutes), "google")
        except RoutesAPIError as exc:
            logger.warning("Routes API failed, falling back to estimates: %s", exc)

    async def estimate(kept: list[int]) -> LoopRoute:
        return estimate_loop(hotel, [points[i] for i in kept], mode)

    return RoutedDay(await route_trimmed(stops, estimate, max_minutes), "estimate")


def trim_value(poi: POI) -> float:
    """What a stop is worth when a day must lose one: its popularity. Hand-picked must-sees
    (no Google rating) are dropped last."""
    return popularity(poi) or math.inf


async def route_trimmed(
    stops: Sequence[POI], route: Callable[[list[int]], Awaitable[LoopRoute]], max_minutes: int | None
) -> LoopRoute:
    """Route the day with `route` (given the indexes of the stops to keep); while it runs over
    `max_minutes`, drop the least popular stop and route again."""
    kept = list(range(len(stops)))
    for attempt in range(MAX_TRIMS_PER_DAY + 1):
        loop = await route(kept)
        loop = LoopRoute(order=[kept[i] for i in loop.order], legs=loop.legs)  # indexes into `stops`
        too_long = max_minutes is not None and loop_minutes(stops, loop) > max_minutes
        if not too_long or len(kept) == 1 or attempt == MAX_TRIMS_PER_DAY:
            return loop
        kept.remove(min(kept, key=lambda i: trim_value(stops[i])))
    raise AssertionError("unreachable")


def loop_minutes(stops: Sequence[POI], loop: LoopRoute) -> float:
    """Visits plus travel for a routed day."""
    return sum(stops[i].avg_duration_min for i in loop.order) + sum(leg.seconds for leg in loop.legs) / 60


def estimate_loop(hotel: LatLng, points: Sequence[LatLng], mode: TravelMode) -> LoopRoute:
    """Nearest-neighbour ordering with straight-line travel estimates."""
    remaining = list(range(len(points)))
    order: list[int] = []
    current = hotel
    while remaining:
        nearest = min(remaining, key=lambda i: haversine_km(current, points[i]))
        order.append(nearest)
        remaining.remove(nearest)
        current = points[nearest]

    path = [hotel, *(points[i] for i in order), hotel]
    return LoopRoute(order=order, legs=[_estimate_leg(a, b, mode) for a, b in pairwise(path)])


def _estimate_leg(a: LatLng, b: LatLng, mode: TravelMode) -> Leg:
    km = haversine_km(a, b) * DETOUR_FACTOR
    return Leg(seconds=round(km / MODE_PROFILES[mode].fallback_speed_kmh * 3600), meters=round(km * 1000))


def build_day(
    day_number: int,
    stops: Sequence[POI],
    routed: RoutedDay,
    day_date: date | None = None,
    weather: DayWeatherOut | None = None,
    rain_adjusted: bool = False,
) -> DayPlan:
    loop = routed.loop
    ordered = [stops[i] for i in loop.order]
    visited = set(loop.order)
    dropped = [stop.name for i, stop in enumerate(stops) if i not in visited]
    planned = [
        PlannedStop(
            order_in_day=position,
            poi_id=poi.id,
            name=poi.name,
            category=poi.category,
            latitude=poi.latitude,
            longitude=poi.longitude,
            visit_minutes=poi.avg_duration_min,
            travel_minutes_from_previous=_minutes(leg.seconds),
            distance_km_from_previous=_km(leg.meters),
            path_from_previous=leg.polyline,
            leg_from_previous=leg_details(leg),
            entry_price=poi.entry_price,
            rating=poi.rating,
            hours=hours_on(poi.opening_hours, day_date) if day_date else None,
        )
        # legs has one extra entry (the way back to the hotel), handled separately below.
        for position, (poi, leg) in enumerate(zip(ordered, loop.legs, strict=False), start=1)
    ]
    back = loop.legs[-1]
    return DayPlan(
        day_number=day_number,
        stops=planned,
        return_travel_minutes=_minutes(back.seconds),
        return_distance_km=_km(back.meters),
        return_path=back.polyline,
        return_leg=leg_details(back),
        total_travel_minutes=_minutes(sum(leg.seconds for leg in loop.legs)),
        total_visit_minutes=sum(poi.avg_duration_min for poi in ordered),
        routing_source=routed.source,
        transit_available=routed.transit_available,
        date=day_date,
        weather=weather,
        rain_adjusted=rain_adjusted,
        dropped_stops=dropped,
    )


def leg_details(leg: Leg) -> LegDetails | None:
    """How a transit-plan leg is travelled; None in walking and driving plans."""
    if leg.mode is None:
        return None
    return LegDetails(
        mode=leg.mode,
        rides=[
            TransitRideOut(
                vehicle=ride.vehicle,
                line=ride.line,
                line_color=ride.line_color,
                line_text_color=ride.line_text_color,
                headsign=ride.headsign,
                from_stop=ride.from_stop,
                to_stop=ride.to_stop,
                stop_count=ride.stop_count,
                minutes=_minutes(ride.seconds),
                agency=ride.agency,
            )
            for ride in leg.rides
        ],
        walk_minutes=_minutes(leg.walk_seconds) if leg.walk_seconds is not None else None,
        alternative_mode=leg.alternative[0] if leg.alternative else None,
        alternative_minutes=_minutes(leg.alternative[1]) if leg.alternative else None,
    )


def _minutes(seconds: int) -> int:
    return round(seconds / 60)


def _km(meters: int) -> float:
    return round(meters / 1000, 1)

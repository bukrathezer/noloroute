"""Trip planning: choose which POIs to visit, split them into days, and order each day.

1. select_stops     Score every POI (popularity, discounted by distance from the hotel) and
                    repeatedly take the best one that still fits the trip's time and budget. Each
                    pick lowers the score of its category, so the trip stays varied.
2. split_into_days  "Sweep": sort the chosen stops by direction from the hotel and cut the circle
                    into `days` consecutive slices of roughly equal time, so each day heads one way.
3. order_day        Google Routes API optimizes the visiting order (hotel -> stops -> hotel) and
                    returns real travel times. If it fails, fall back to nearest-neighbour ordering
                    with straight-line time estimates so a plan is always returned.
"""

import asyncio
import logging
import math
import re
import unicodedata
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from itertools import pairwise
from typing import Literal

from app.models import POI
from app.schemas.route import DayPlan, PlannedStop
from app.services.geo import LatLng, bearing_rad, haversine_km
from app.services.routes_client import Leg, LoopRoute, RoutesAPIError, RoutesClient, TravelMode

logger = logging.getLogger(__name__)

DAY_MINUTES = 8 * 60  # sightseeing time per day, travel included
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
}
DETOUR_FACTOR = 1.3  # streets aren't straight lines

RoutingSource = Literal["google", "estimate"]


class HotelTooFarError(ValueError):
    pass


async def plan_trip(
    pois: Sequence[POI],
    hotel: LatLng,
    days: int,
    budget: Decimal | None,
    mode: TravelMode,
    routes_client: RoutesClient | None,
) -> list[DayPlan]:
    if not pois or min(haversine_km(hotel, location(p)) for p in pois) > MAX_HOTEL_DISTANCE_KM:
        raise HotelTooFarError(f"Accommodation is more than {MAX_HOTEL_DISTANCE_KM:g} km from every sight")

    chosen = select_stops(pois, hotel, days, budget, mode)
    groups = split_into_days(chosen, hotel, days, mode)
    # Days are independent, so route them concurrently.
    routed = await asyncio.gather(*(order_day(hotel, group, mode, routes_client) for group in groups))
    return [
        build_day(day_number, group, loop, source)
        for day_number, (group, (loop, source)) in enumerate(zip(groups, routed, strict=True), start=1)
    ]


def location(poi: POI) -> LatLng:
    return LatLng(poi.latitude, poi.longitude)


def popularity(poi: POI) -> float | None:
    """rating x log10(reviews)^2: grows with review count, with diminishing returns."""
    if poi.rating is None or not poi.user_rating_count:
        return None
    return poi.rating * math.log10(1 + poi.user_rating_count) ** 2


def stop_minutes(poi: POI, mode: TravelMode) -> int:
    return poi.avg_duration_min + MODE_PROFILES[mode].travel_min_per_stop


def select_stops(pois: Sequence[POI], hotel: LatLng, days: int, budget: Decimal | None, mode: TravelMode) -> list[POI]:
    """Greedy: repeatedly take the highest (category-adjusted) score that still fits."""
    half_score_km = MODE_PROFILES[mode].distance_half_score_km
    known = sorted(p for p in map(popularity, pois) if p is not None)
    curated_popularity = known[int(CURATED_POPULARITY_PERCENTILE * (len(known) - 1))] if known else 1.0

    def base_score(poi: POI) -> float:
        pop = popularity(poi) or curated_popularity
        return pop / (1 + haversine_km(hotel, location(poi)) / half_score_km)

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
        return not is_near_duplicate(poi, chosen)

    candidates = list(pois)
    while True:
        # Time and money only get used up, so a POI that doesn't fit now never will.
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
    """Sweep: walk around the hotel by direction, closing a day once it reaches its share of time."""
    ordered = _sort_by_direction(stops, hotel)
    remaining_minutes = sum(stop_minutes(s, mode) for s in ordered)
    groups: list[list[POI]] = []
    current: list[POI] = []
    current_minutes = 0

    for i, stop in enumerate(ordered):
        minutes = stop_minutes(stop, mode)
        days_left = days - len(groups)  # including the current day
        stops_left = len(ordered) - i  # including this stop
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


def _sort_by_direction(stops: Sequence[POI], hotel: LatLng) -> list[POI]:
    if len(stops) < 2:
        return list(stops)
    by_angle = sorted(stops, key=lambda s: bearing_rad(hotel, location(s)))
    angles = [bearing_rad(hotel, location(s)) for s in by_angle]
    n = len(angles)
    # Start just after the widest empty direction, so no day is split across a dense cluster.
    gaps = [(angles[(i + 1) % n] - angles[i]) % (2 * math.pi) for i in range(n)]
    start = (max(range(n), key=gaps.__getitem__) + 1) % n
    return by_angle[start:] + by_angle[:start]


async def order_day(
    hotel: LatLng, stops: Sequence[POI], mode: TravelMode, routes_client: RoutesClient | None
) -> tuple[LoopRoute, RoutingSource]:
    if not stops:
        return LoopRoute(order=[], legs=[Leg(seconds=0, meters=0)]), "estimate"
    points = [location(s) for s in stops]
    if routes_client is not None:
        try:
            return await routes_client.optimize_loop(hotel, points, mode), "google"
        except RoutesAPIError as exc:
            logger.warning("Routes API failed, falling back to estimates: %s", exc)
    return estimate_loop(hotel, points, mode), "estimate"


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


def build_day(day_number: int, stops: Sequence[POI], loop: LoopRoute, source: RoutingSource) -> DayPlan:
    ordered = [stops[i] for i in loop.order]
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
            entry_price=poi.entry_price,
            rating=poi.rating,
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
        total_travel_minutes=_minutes(sum(leg.seconds for leg in loop.legs)),
        total_visit_minutes=sum(poi.avg_duration_min for poi in ordered),
        routing_source=source,
    )


def _minutes(seconds: int) -> int:
    return round(seconds / 60)


def _km(meters: int) -> float:
    return round(meters / 1000, 1)

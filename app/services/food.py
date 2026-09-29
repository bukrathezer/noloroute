"""Food suggestions along a day's route: popular restaurants a short walk from its stops.

They are suggestions, not stops: when and where to eat is personal, so the planner leaves meals
out and the traveller asks for places per day. They are fetched live and never stored (Google's
terms allow storing only place IDs).

Where to look: two stops about a third and two thirds of the way through the day, so the
suggestions cover the route rather than one spot. Around each, one Nearby Search asks for the
20 most popular restaurants, bakeries and dessert shops within a ten-minute walk; the well-rated
ones that are open for a meal that day are ranked by popularity, each is listed under the stop it
is nearest to, and a chain shows up once, with its best branch.
"""

import asyncio
import json
import math
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.services.geo import LatLng, haversine_km
from app.services.opening_hours import google_weekday, hours_on, open_minutes, parse_periods
from app.services.place_search import PlaceSearchClient

FOOD_TYPES = ["restaurant", "bakery", "dessert_shop"]
EXCLUDED_PRIMARY_TYPES = ["fast_food_restaurant", "meal_takeaway"]
FOOD_FIELDS = ",".join(
    f"places.{field}"
    for field in [
        "id",
        "displayName",
        "location",
        "primaryTypeDisplayName",  # "Turkish restaurant", in the requested language
        "rating",
        "userRatingCount",
        "priceLevel",
        "regularOpeningHours",
        "businessStatus",
        "googleMapsUri",
    ]
)
SEARCH_RADIUS_M = 700.0  # about a ten-minute walk
MAX_ANCHORS = 2
PER_ANCHOR = 4
MIN_RATING = 4.2
MIN_REVIEWS = 200
# Open at least an hour within lunch or dinner time (minutes after midnight).
MEAL_WINDOWS = ((11 * 60 + 30, 15 * 60), (18 * 60, 22 * 60 + 30))
MIN_MEAL_MINUTES = 60
PRICE_LEVELS = {
    "PRICE_LEVEL_FREE": 0,
    "PRICE_LEVEL_INEXPENSIVE": 1,
    "PRICE_LEVEL_MODERATE": 2,
    "PRICE_LEVEL_EXPENSIVE": 3,
    "PRICE_LEVEL_VERY_EXPENSIVE": 4,
}


@dataclass(frozen=True)
class Stop:
    name: str
    location: LatLng


@dataclass(frozen=True)
class FoodPlace:
    place_id: str
    name: str
    cuisine: str | None
    location: LatLng
    rating: float
    rating_count: int
    price_level: int | None  # 0 (free) to 4 (very expensive)
    hours: str | None  # that day's hours, e.g. "11:00–23:00"; None without a date or data
    maps_url: str | None
    distance_m: int  # from the stop it is listed under


@dataclass(frozen=True)
class FoodGroup:
    near: str  # the stop's name
    places: list[FoodPlace]


def pick_anchors(stops: Sequence[Stop]) -> list[Stop]:
    """Up to MAX_ANCHORS stops spread evenly along the day (a third and two thirds in)."""
    n = len(stops)
    if n <= MAX_ANCHORS:
        return list(stops)
    positions = sorted({round(k * (n + 1) / (MAX_ANCHORS + 1)) - 1 for k in range(1, MAX_ANCHORS + 1)})
    return [stops[i] for i in positions]


async def food_suggestions(
    client: PlaceSearchClient, stops: Sequence[Stop], day: date | None, language: str
) -> list[FoodGroup]:
    anchors = pick_anchors(stops)
    responses = await asyncio.gather(
        *(
            client.search_nearby(
                a.location,
                SEARCH_RADIUS_M,
                FOOD_TYPES,
                FOOD_FIELDS,
                language,
                excluded_primary_types=EXCLUDED_PRIMARY_TYPES,
            )
            for a in anchors
        )
    )
    candidates: dict[str, FoodPlace] = {}
    for places in responses:
        for place in places:
            food = to_food_place(place, day)
            if food is not None:
                candidates[food.place_id] = food

    # Best first; each place under the anchor it is nearest to; one branch per chain.
    groups: dict[int, list[FoodPlace]] = {i: [] for i in range(len(anchors))}
    brands: set[str] = set()
    for food in sorted(candidates.values(), key=_popularity, reverse=True):
        if (brand := _brand(food.name)) in brands:
            continue
        brands.add(brand)
        distances = [haversine_km(a.location, food.location) for a in anchors]
        nearest = min(range(len(anchors)), key=distances.__getitem__)
        groups[nearest].append(_with_distance(food, distances[nearest]))
    return [FoodGroup(near=anchors[i].name, places=groups[i][:PER_ANCHOR]) for i in range(len(anchors)) if groups[i]]


def to_food_place(place: dict[str, Any], day: date | None) -> FoodPlace | None:
    """A Nearby Search result as a suggestion, or None if it isn't good enough or open enough."""
    rating, count = place.get("rating"), place.get("userRatingCount", 0)
    if place.get("businessStatus", "OPERATIONAL") != "OPERATIONAL" or rating is None:
        return None
    if rating < MIN_RATING or count < MIN_REVIEWS:
        return None
    periods = (place.get("regularOpeningHours") or {}).get("periods")
    periods_json = json.dumps(periods) if periods else None
    if day is not None and not open_for_a_meal(periods_json, day):
        return None
    loc = place["location"]
    return FoodPlace(
        place_id=place["id"],
        name=place.get("displayName", {}).get("text", ""),
        cuisine=place.get("primaryTypeDisplayName", {}).get("text"),
        location=LatLng(loc["latitude"], loc["longitude"]),
        rating=rating,
        rating_count=count,
        price_level=PRICE_LEVELS.get(place.get("priceLevel", "")),
        hours=hours_on(periods_json, day) if day else None,
        maps_url=place.get("googleMapsUri"),
        distance_m=0,
    )


def open_for_a_meal(periods_json: str | None, day: date) -> bool:
    """Open for at least an hour at lunch or dinner time that day (unknown hours count as open)."""
    intervals = parse_periods(periods_json)
    weekday = google_weekday(day)
    return any(open_minutes(intervals, weekday, window) >= MIN_MEAL_MINUTES for window in MEAL_WINDOWS)


def _popularity(food: FoodPlace) -> float:
    # The same measure as for sights: rating x log10(reviews)^2.
    return food.rating * math.log10(1 + food.rating_count) ** 2


def _brand(name: str) -> str:
    """The first two words of a name, which branches of a chain share ("Hafız Mustafa 1864 Sirkeci")."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return " ".join(re.findall(r"[a-z0-9]+", ascii_name)[:2])


def _with_distance(food: FoodPlace, km: float) -> FoodPlace:
    return FoodPlace(**{**vars(food), "distance_m": round(km * 1000)})

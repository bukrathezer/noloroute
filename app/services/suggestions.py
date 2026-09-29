"""Suggestions around a planned day that are not part of its route: places to eat along it, and
nightlife for the evening.

They are suggestions, not stops: when and where to eat or go out is personal, so the planner
leaves them out and the traveller asks per day. They are fetched live and never stored (Google's
terms allow storing only place IDs).

For each kind, a few anchor points are chosen (see food_anchors and nightlife_anchors). Around
each, one Nearby Search asks for the 20 most popular places of the kind's types; those rated well
enough and open long enough in the kind's hours that day are ranked by popularity, each is listed
under the anchor it is nearest to, and a chain shows up once, with its best branch.
"""

import asyncio
import json
import math
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date
from typing import Any

from app.services.geo import LatLng, haversine_km
from app.services.opening_hours import google_weekday, hours_on, open_minutes, parse_periods
from app.services.place_search import PlaceSearchClient

FIELDS = ",".join(
    f"places.{field}"
    for field in [
        "id",
        "displayName",
        "location",
        "primaryTypeDisplayName",  # "Turkish restaurant", "Cocktail bar", in the requested language
        "rating",
        "userRatingCount",
        "priceLevel",
        "regularOpeningHours",
        "businessStatus",
        "googleMapsUri",
    ]
)
PRICE_LEVELS = {
    "PRICE_LEVEL_FREE": 0,
    "PRICE_LEVEL_INEXPENSIVE": 1,
    "PRICE_LEVEL_MODERATE": 2,
    "PRICE_LEVEL_EXPENSIVE": 3,
    "PRICE_LEVEL_VERY_EXPENSIVE": 4,
}
PER_ANCHOR = 4
MIN_OPEN_MINUTES = 60  # open at least this long within one of the kind's time windows


@dataclass(frozen=True)
class Kind:
    types: list[str]
    excluded_primary_types: list[str]
    radius_m: float
    min_rating: float
    min_reviews: int
    windows: tuple[tuple[int, int], ...]  # minutes after midnight; may run past midnight (e.g. 26:00)
    primary_types_only: bool = False  # match only places whose main type is one of `types`


FOOD = Kind(
    types=["restaurant", "bakery", "dessert_shop"],
    excluded_primary_types=["fast_food_restaurant", "meal_takeaway"],
    radius_m=700,  # about a ten-minute walk
    min_rating=4.2,
    min_reviews=200,
    windows=((11 * 60 + 30, 15 * 60), (18 * 60, 22 * 60 + 30)),  # lunch, dinner
)
NIGHTLIFE = Kind(
    types=[
        "night_club",
        "bar",
        "pub",
        "wine_bar",
        "cocktail_bar",
        "live_music_venue",
        "comedy_club",
        "beer_garden",
        "hookah_bar",
    ],
    excluded_primary_types=[],
    radius_m=1000,  # a short walk or ride from where the day ends
    min_rating=4.2,
    min_reviews=100,
    windows=((20 * 60, 26 * 60),),  # 20:00 to 02:00
    primary_types_only=True,  # not restaurants that happen to have a bar
)
FOOD_ANCHORS = 2  # stops spread along the day
NIGHTLIFE_EXTRA_ANCHOR_KM = 1.5  # also look near the last stop if it is at least this far from the hotel


@dataclass(frozen=True)
class Anchor:
    name: str | None  # a stop's name; None for the accommodation
    location: LatLng


@dataclass(frozen=True)
class Suggestion:
    place_id: str
    name: str
    category: str | None  # "Turkish restaurant", "Cocktail bar"
    location: LatLng
    rating: float
    rating_count: int
    price_level: int | None  # 0 (free) to 4 (very expensive)
    hours: str | None  # that day's hours, e.g. "18:00–02:00"; None without a date or data
    maps_url: str | None
    distance_m: int = 0  # from the anchor it is listed under


@dataclass(frozen=True)
class Group:
    near: str | None  # the anchor's name; None for the accommodation
    places: list[Suggestion]


def food_anchors(stops: Sequence[Anchor]) -> list[Anchor]:
    """Up to two stops spread evenly along the day (a third and two thirds in)."""
    n = len(stops)
    if n <= FOOD_ANCHORS:
        return list(stops)
    positions = sorted({round(k * (n + 1) / (FOOD_ANCHORS + 1)) - 1 for k in range(1, FOOD_ANCHORS + 1)})
    return [stops[i] for i in positions]


def nightlife_anchors(hotel: LatLng, stops: Sequence[Anchor]) -> list[Anchor]:
    """Where the day ends: the accommodation, and the last stop if it is well away from it."""
    anchors = [Anchor(None, hotel)]
    if stops and haversine_km(hotel, stops[-1].location) >= NIGHTLIFE_EXTRA_ANCHOR_KM:
        anchors.append(stops[-1])
    return anchors


async def suggestions(
    client: PlaceSearchClient, anchors: Sequence[Anchor], kind: Kind, day: date | None, language: str
) -> list[Group]:
    responses = await asyncio.gather(
        *(
            client.search_nearby(
                a.location,
                kind.radius_m,
                kind.types,
                FIELDS,
                language,
                excluded_primary_types=kind.excluded_primary_types,
                primary_types_only=kind.primary_types_only,
            )
            for a in anchors
        )
    )
    candidates: dict[str, Suggestion] = {}
    for places in responses:
        for place in places:
            suggestion = to_suggestion(place, kind, day)
            if suggestion is not None:
                candidates[suggestion.place_id] = suggestion

    # Best first; each place under the anchor it is nearest to; one branch per chain.
    groups: list[list[Suggestion]] = [[] for _ in anchors]
    brands: set[str] = set()
    for place in sorted(candidates.values(), key=_popularity, reverse=True):
        if (brand := _brand(place.name)) in brands:
            continue
        brands.add(brand)
        distances = [haversine_km(a.location, place.location) for a in anchors]
        nearest = min(range(len(anchors)), key=distances.__getitem__)
        groups[nearest].append(replace(place, distance_m=round(distances[nearest] * 1000)))
    return [Group(a.name, places[:PER_ANCHOR]) for a, places in zip(anchors, groups, strict=True) if places]


def to_suggestion(place: dict[str, Any], kind: Kind, day: date | None) -> Suggestion | None:
    """A Nearby Search result as a suggestion, or None if it isn't good enough or open enough."""
    rating, count = place.get("rating"), place.get("userRatingCount", 0)
    if place.get("businessStatus", "OPERATIONAL") != "OPERATIONAL" or rating is None:
        return None
    if rating < kind.min_rating or count < kind.min_reviews:
        return None
    periods = (place.get("regularOpeningHours") or {}).get("periods")
    periods_json = json.dumps(periods) if periods else None
    if day is not None and not open_in_windows(periods_json, day, kind.windows):
        return None
    loc = place["location"]
    return Suggestion(
        place_id=place["id"],
        name=place.get("displayName", {}).get("text", ""),
        category=place.get("primaryTypeDisplayName", {}).get("text"),
        location=LatLng(loc["latitude"], loc["longitude"]),
        rating=rating,
        rating_count=count,
        price_level=PRICE_LEVELS.get(place.get("priceLevel", "")),
        hours=hours_on(periods_json, day) if day else None,
        maps_url=place.get("googleMapsUri"),
    )


def open_in_windows(periods_json: str | None, day: date, windows: Sequence[tuple[int, int]]) -> bool:
    """Open for at least an hour in one of the windows that day (unknown hours count as open)."""
    intervals = parse_periods(periods_json)
    weekday = google_weekday(day)
    return any(open_minutes(intervals, weekday, window) >= MIN_OPEN_MINUTES for window in windows)


def _popularity(place: Suggestion) -> float:
    # The same measure as for sights: rating x log10(reviews)^2.
    return place.rating * math.log10(1 + place.rating_count) ** 2


def _brand(name: str) -> str:
    """The first two words of a name, which branches of a chain share ("Hafız Mustafa 1864 Sirkeci")."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return " ".join(re.findall(r"[a-z0-9]+", ascii_name)[:2])

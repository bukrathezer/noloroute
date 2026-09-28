"""Fetch POIs for Paris and Istanbul from Google Places and sync them into the DB.

How it works: each city's bounding box is split into a grid of overlapping circles. For every
circle and category we ask Nearby Search for the 20 most *popular* places, then deduplicate on
Google's place_id, drop obscure/irrelevant places and upsert the rest. A couple of text searches
fill gaps that Google's type system misses (scenic viewpoints, bazaars). Famous streets and
districts (e.g. Champs-Elysees, Istiklal Avenue) are poorly represented in Places, so they are
added from a small hand-entered list (CURATED_POIS).

Safe to re-run: existing POIs are updated, and POIs that no longer pass the filters are removed
(unless a saved route references them).

Usage (from the repo root):
    python -m scripts.ingest_places                    # all cities
    python -m scripts.ingest_places --city paris
    python -m scripts.ingest_places --dry-run          # fetch and summarize, don't write to the DB
    python -m scripts.ingest_places --use-cache        # reuse the last raw API results (no API calls)
"""

import argparse
import json
import math
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.config import get_settings
from app.db.base import new_id
from app.db.session import SessionLocal
from app.models import POI, City
from app.models.poi import POICategory
from app.services.geo import LatLng
from app.services.places_client import BoundingBox, PlacesAPIError, PlacesClient

CACHE_DIR = Path(__file__).resolve().parents[1] / ".cache" / "places"


@dataclass(frozen=True)
class CityConfig:
    id: str
    name: str
    currency_code: str
    bounds: BoundingBox


CITIES = {
    "paris": CityConfig("paris", "Paris", "EUR", BoundingBox(48.815, 2.224, 48.902, 2.470)),
    # Historic peninsula, Beyoglu, Besiktas, Uskudar, Kadikoy and the Bosphorus shore up to Sariyer.
    "istanbul": CityConfig("istanbul", "Istanbul", "TRY", BoundingBox(40.960, 28.840, 41.130, 29.100)),
}


@dataclass(frozen=True)
class CuratedPOI:
    slug: str
    name: str
    lat: float
    lng: float
    avg_duration_min: int
    category: POICategory = POICategory.LANDMARK


# Must-see streets and districts. Places returns them as unrated "neighborhood" entries or as
# unrelated businesses (a cafe, a tram stop, a mall), so they are entered by hand.
CURATED_POIS: dict[str, list[CuratedPOI]] = {
    "paris": [
        CuratedPOI("champs-elysees", "Avenue des Champs-Élysées", 48.8698, 2.3076, 60),
        CuratedPOI("montmartre", "Montmartre", 48.8865, 2.3408, 120),
        CuratedPOI("le-marais", "Le Marais", 48.8575, 2.3590, 120),
        CuratedPOI("canal-saint-martin", "Canal Saint-Martin", 48.8710, 2.3650, 60),
    ],
    "istanbul": [
        CuratedPOI("istiklal-avenue", "İstiklal Avenue", 41.0337, 28.9778, 90),
        CuratedPOI("pierre-loti-hill", "Pierre Loti Hill", 41.0535, 28.9335, 60, POICategory.VIEWPOINT),
        CuratedPOI("balat", "Balat", 41.0296, 28.9483, 90),
    ],
}

GRID_STEP_KM = 4.0
# Circles must reach the grid cell corners (half the diagonal = 0.707 * step) to leave no gaps.
GRID_RADIUS_M = GRID_STEP_KM * 1000 * 0.75
KM_PER_DEG_LAT = 111.32

# One Nearby Search per grid cell per group. The group label is only for logging: a place's
# category comes from its own Google types (see categorize).
NEARBY_GROUPS: list[tuple[POICategory, list[str]]] = [
    (POICategory.MUSEUM, ["museum", "art_gallery"]),
    (POICategory.LANDMARK, ["tourist_attraction", "historical_landmark", "monument", "cultural_landmark", "historical_place"]),
    (POICategory.PARK, ["park", "botanical_garden", "garden"]),
    (POICategory.RELIGIOUS_SITE, ["church", "mosque", "synagogue", "hindu_temple"]),
    (POICategory.VIEWPOINT, ["observation_deck", "scenic_spot"]),
    (POICategory.MARKET, ["market"]),
]  # fmt: skip

# Text searches for places Google doesn't type consistently.
TEXT_SEARCHES = ["scenic viewpoint", "historic bazaar"]

# Allowlist: a place is kept only if its primaryType is listed here, which also decides its
# category. Google has hundreds of types, so blocklisting (restaurants, hypermarkets, garden
# centers, ...) can't keep up. Places without a primaryType fall back to their other types,
# checked in this dict's order.
TYPE_TO_CATEGORY: dict[str, POICategory] = {
    "church": POICategory.RELIGIOUS_SITE,
    "mosque": POICategory.RELIGIOUS_SITE,
    "synagogue": POICategory.RELIGIOUS_SITE,
    "hindu_temple": POICategory.RELIGIOUS_SITE,
    "place_of_worship": POICategory.RELIGIOUS_SITE,
    "museum": POICategory.MUSEUM,
    "art_gallery": POICategory.MUSEUM,
    "art_museum": POICategory.MUSEUM,
    "history_museum": POICategory.MUSEUM,
    "park": POICategory.PARK,
    "city_park": POICategory.PARK,
    "national_park": POICategory.PARK,
    "botanical_garden": POICategory.PARK,
    "garden": POICategory.PARK,
    "observation_deck": POICategory.VIEWPOINT,
    "scenic_spot": POICategory.VIEWPOINT,
    "market": POICategory.MARKET,
    "flea_market": POICategory.MARKET,
    "historical_landmark": POICategory.LANDMARK,
    "historical_place": POICategory.LANDMARK,
    "monument": POICategory.LANDMARK,
    "cultural_landmark": POICategory.LANDMARK,
    "castle": POICategory.LANDMARK,
    "palace": POICategory.LANDMARK,
    "bridge": POICategory.LANDMARK,
    "plaza": POICategory.LANDMARK,
    "fountain": POICategory.LANDMARK,
    "sculpture": POICategory.LANDMARK,
    "opera_house": POICategory.LANDMARK,
    "cemetery": POICategory.LANDMARK,
    "tourist_attraction": POICategory.LANDMARK,
    "aquarium": POICategory.OTHER,
}

# Minimum Google review count: filters out obscure places, keeps what tourists actually visit.
MIN_RATING_COUNT = 300

DEFAULT_DURATION_MIN = {
    POICategory.MUSEUM: 120,
    POICategory.LANDMARK: 60,
    POICategory.PARK: 60,
    POICategory.RELIGIOUS_SITE: 45,
    POICategory.VIEWPOINT: 30,
    POICategory.MARKET: 60,
    POICategory.OTHER: 45,
}

RawResult = dict[str, Any]  # {"source": <search that found it>, "place": <Places API place dict>}


def grid_centers(bounds: BoundingBox, step_km: float) -> list[LatLng]:
    mid_lat = (bounds.south + bounds.north) / 2
    lat_step = step_km / KM_PER_DEG_LAT
    lng_step = step_km / (KM_PER_DEG_LAT * math.cos(math.radians(mid_lat)))
    rows = max(1, math.ceil((bounds.north - bounds.south) / lat_step))
    cols = max(1, math.ceil((bounds.east - bounds.west) / lng_step))
    return [
        LatLng(bounds.south + (r + 0.5) * lat_step, bounds.west + (c + 0.5) * lng_step)
        for r in range(rows)
        for c in range(cols)
    ]


def fetch_raw(client: PlacesClient, city: CityConfig) -> list[RawResult]:
    centers = grid_centers(city.bounds, GRID_STEP_KM)
    print(f"  grid: {len(centers)} cells x {len(NEARBY_GROUPS)} groups + {len(TEXT_SEARCHES)} text searches")
    results: list[RawResult] = []

    for group, types in NEARBY_GROUPS:
        fetched = 0
        for center in centers:
            try:
                places = client.search_nearby(center, GRID_RADIUS_M, types)
            except PlacesAPIError as exc:
                # A 400 means the request itself is invalid (e.g. an unknown type): every cell would fail.
                print(f"  ! skipped group {group.value}: {exc}", file=sys.stderr)
                break
            results += [{"source": f"nearby:{group.value}", "place": p} for p in places]
            fetched += len(places)
        print(f"  nearby {group.value:15} fetched {fetched}")

    for query in TEXT_SEARCHES:
        places = list(client.search_text(query, city.bounds))
        results += [{"source": f"text:{query}", "place": p} for p in places]
        print(f"  text   {query!r:17} fetched {len(places)}")

    return results


def categorize(place: dict[str, Any]) -> POICategory | None:
    """Map a place to our category, or None if it isn't a sightseeing place."""
    primary = place.get("primaryType")
    if primary:
        return TYPE_TO_CATEGORY.get(primary)
    types = set(place.get("types", []))
    for google_type, category in TYPE_TO_CATEGORY.items():
        if google_type in types:
            return category
    return None


def is_relevant(place: dict[str, Any], bounds: BoundingBox) -> bool:
    if place.get("businessStatus", "OPERATIONAL") != "OPERATIONAL":
        return False
    if place.get("userRatingCount", 0) < MIN_RATING_COUNT:
        return False
    # Grid circles overlap the bounding box edges.
    loc = place["location"]
    return bounds.south <= loc["latitude"] <= bounds.north and bounds.west <= loc["longitude"] <= bounds.east


def to_row(place: dict[str, Any], city_id: str, category: POICategory) -> dict[str, Any]:
    periods = place.get("regularOpeningHours", {}).get("periods")
    return {
        "id": new_id(),
        "city_id": city_id,
        "place_id": place["id"],
        "name": place["displayName"]["text"],
        "category": category.value,
        "latitude": place["location"]["latitude"],
        "longitude": place["location"]["longitude"],
        "avg_duration_min": DEFAULT_DURATION_MIN[category],
        "opening_hours": json.dumps(periods) if periods else None,
        "rating": place.get("rating"),
        "user_rating_count": place.get("userRatingCount"),
    }


def build_rows(raw: list[RawResult], city: CityConfig) -> list[dict[str, Any]]:
    """Deduplicate on place_id, filter, categorize and convert to DB rows."""
    rows_by_place_id: dict[str, dict[str, Any]] = {}
    for item in raw:
        place = item["place"]
        if place["id"] in rows_by_place_id or not is_relevant(place, city.bounds):
            continue
        category = categorize(place)
        if category is not None:
            rows_by_place_id[place["id"]] = to_row(place, city.id, category)
    return list(rows_by_place_id.values()) + curated_rows(city)


def curated_rows(city: CityConfig) -> list[dict[str, Any]]:
    return [
        {
            "id": new_id(),
            "city_id": city.id,
            "place_id": f"curated:{city.id}:{poi.slug}",  # not a Google ID; keeps upserts idempotent
            "name": poi.name,
            "category": poi.category.value,
            "latitude": poi.lat,
            "longitude": poi.lng,
            "avg_duration_min": poi.avg_duration_min,
            "opening_hours": None,  # open-air, always accessible
            "rating": None,
            "user_rating_count": None,
        }
        for poi in CURATED_POIS.get(city.id, [])
    ]


def save_city(city: CityConfig, rows: list[dict[str, Any]]) -> int:
    """Upsert the city and its POIs; return how many stale POIs were removed."""
    with SessionLocal() as db:
        city_stmt = pg_insert(City).values(id=city.id, name=city.name, currency_code=city.currency_code)
        db.execute(
            city_stmt.on_conflict_do_update(
                index_elements=[City.id],
                set_={"name": city_stmt.excluded.name, "currency_code": city_stmt.excluded.currency_code},
            )
        )
        if rows:
            poi_stmt = pg_insert(POI).values(rows)
            # Refresh Google-sourced fields; keep id, avg_duration_min and entry_price, which may
            # have been tuned by hand.
            refreshed = ["name", "category", "latitude", "longitude", "opening_hours", "rating", "user_rating_count"]
            db.execute(
                poi_stmt.on_conflict_do_update(
                    index_elements=[POI.place_id],
                    set_={col: poi_stmt.excluded[col] for col in refreshed},
                )
            )
        removed = db.execute(
            delete(POI).where(
                POI.city_id == city.id,
                POI.place_id.not_in([r["place_id"] for r in rows]),
                ~POI.route_stops.any(),
            )
        ).rowcount
        db.commit()
    return removed


def print_summary(rows: list[dict[str, Any]]) -> None:
    counts = Counter(row["category"] for row in rows)
    print(f"  kept {len(rows)}: " + "  ".join(f"{cat}={n}" for cat, n in sorted(counts.items())))
    for category in sorted(counts):
        top = sorted(
            (r for r in rows if r["category"] == category), key=lambda r: -(r["user_rating_count"] or 0)
        )[:8]
        print(f"    {category:15} " + ", ".join(r["name"] for r in top))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--city", choices=sorted(CITIES), help="ingest a single city (default: all)")
    parser.add_argument("--dry-run", action="store_true", help="fetch and summarize without writing to the DB")
    parser.add_argument("--use-cache", action="store_true", help="reuse cached raw results instead of calling the API")
    args = parser.parse_args()

    cities = [CITIES[args.city]] if args.city else list(CITIES.values())
    api_key = get_settings().google_places_api_key
    if not args.use_cache and not api_key:
        sys.exit("GOOGLE_PLACES_API_KEY is not set in .env")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with PlacesClient(api_key or "") as client:
        for city in cities:
            print(f"== {city.name}")
            cache_file = CACHE_DIR / f"{city.id}.json"
            if args.use_cache:
                raw = json.loads(cache_file.read_text(encoding="utf-8"))
                print(f"  loaded {len(raw)} raw results from {cache_file.name}")
            else:
                raw = fetch_raw(client, city)
                cache_file.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

            rows = build_rows(raw, city)
            print_summary(rows)
            if not args.dry_run:
                removed = save_city(city, rows)
                print(f"  saved {len(rows)} POIs, removed {removed} stale")


if __name__ == "__main__":
    main()

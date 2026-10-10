"""Fetch a city's sights from Google Places and sync them into the DB.

How it works: Nearby Search, asking for the most *popular* places of our types, over an adaptive
grid (see fetch_adaptive: Nearby Search costs about $35 per 1,000 requests, so a city takes as few
as it can). Results are deduplicated on Google's place_id, obscure/irrelevant places dropped (and
"markets" that are shops, and second listings of a place at the same spot) and the rest upserted.
A couple of text searches fill gaps that Google's type system misses (scenic viewpoints, bazaars),
and famous sights the popularity search missed are looked up by name (find_famous_sights).
Famous streets and districts (e.g. Champs-Elysees, Istiklal Avenue) are poorly represented in
Places, so they are added from a small hand-entered list (CURATED_POIS).
Visit times and entry prices come from scripts/sight_details.py: rules for every place,
hand-checked values for the most visited ones. New places then get a short description from
Wikipedia (scripts/describe_pois.py).

Paris and Istanbul have hand-drawn search areas (CITIES); the other cities come from
scripts/city_catalog.py, searched around the centre Google gives for their name.

Safe to re-run: existing POIs are updated, and POIs that no longer pass the filters are removed
(unless a saved route references them).

Usage (from the repo root):
    python -m scripts.ingest_places                    # Paris and Istanbul
    python -m scripts.ingest_places --city rome --city kyoto --max-requests 200
    python -m scripts.ingest_places --refresh --max-requests 900   # the monthly refresh
    python -m scripts.ingest_places --city rome --dry-run          # fetch and summarize only
    python -m scripts.ingest_places --city rome --use-cache        # reuse the last raw results
    python -m scripts.ingest_places --repair                       # cities in the DB, current rules
"""

import argparse
import heapq
import json
import math
import os
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.config import get_settings
from app.db.base import new_id
from app.db.session import SessionLocal
from app.models import POI, City
from app.models.poi import POICategory
from app.services.geo import LatLng, haversine_km
from app.services.places_client import MAX_NEARBY_RESULTS, BoundingBox, PlacesAPIError, PlacesClient
from app.services.route_optimizer import SAME_SPOT_KM, SECOND_LISTING_SHARE, distinctive_words
from app.services.wikipedia import WikiClient, WikiError, name_score
from scripts.city_catalog import CATALOG, CatalogCity
from scripts.describe_pois import describe_new_places
from scripts.sight_details import CITY_PRICES, SIGHTS, estimate_entry_price, estimate_visit_minutes

# Raw API results are cached here. Override with PLACES_CACHE_DIR where the repo folder is
# read-only (the Docker image points it at /tmp).
CACHE_DIR = Path(os.environ.get("PLACES_CACHE_DIR") or Path(__file__).resolve().parents[1] / ".cache" / "places")


@dataclass(frozen=True)
class CityConfig:
    id: str
    name: str
    currency_code: str
    timezone: str  # IANA name; transit timetables are read in local time
    bounds: BoundingBox
    name_tr: str | None = None
    country_code: str | None = None


# Hand-drawn search areas; catalog cities get a square around their centre.
CITIES = {
    "paris": CityConfig(
        "paris",
        "Paris",
        "EUR",
        "Europe/Paris",
        BoundingBox(48.815, 2.224, 48.902, 2.470),
        name_tr="Paris",
        country_code="FR",
    ),
    # Historic peninsula, Beyoglu, Besiktas, Uskudar, Kadikoy and the Bosphorus shore up to Sariyer.
    "istanbul": CityConfig(
        "istanbul",
        "Istanbul",
        "TRY",
        "Europe/Istanbul",
        BoundingBox(40.960, 28.840, 41.130, 29.100),
        name_tr="İstanbul",
        country_code="TR",
    ),
}
# A city's cost before its first run (afterwards the last run's count is used).
EXPECTED_CITY_REQUESTS = 100
# The monthly refresh leaves cities alone that were refreshed this recently.
REFRESH_MIN_AGE_DAYS = 25


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

KM_PER_DEG_LAT = 111.32

# The Google types searched for, grouped for reading. A place's category comes from its own
# Google types (see categorize).
NEARBY_GROUPS: list[tuple[POICategory, list[str]]] = [
    (POICategory.MUSEUM, ["museum", "art_gallery"]),
    (
        POICategory.LANDMARK,
        ["tourist_attraction", "historical_landmark", "monument", "cultural_landmark", "historical_place"],
    ),
    (POICategory.PARK, ["park", "botanical_garden", "garden"]),
    (POICategory.RELIGIOUS_SITE, ["church", "mosque", "synagogue", "hindu_temple", "buddhist_temple", "shinto_shrine"]),
    (POICategory.VIEWPOINT, ["observation_deck", "scenic_spot"]),
    (POICategory.MARKET, ["market"]),
]  # fmt: skip

# Adaptive search: all types in one request per cell, cells split while they may still hide
# one of the city's ADAPTIVE_TOP_N most popular sights.
ADAPTIVE_TYPES = sorted({t for _, types in NEARBY_GROUPS for t in types})
ADAPTIVE_TOP_N = 100  # plenty for a week: a 7-day trip has about 45 stops
ADAPTIVE_RADIUS_KM = 12.0  # around the centre of a catalog city
MIN_CELL_KM = 1.0

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
    "buddhist_temple": POICategory.RELIGIOUS_SITE,
    "shinto_shrine": POICategory.RELIGIOUS_SITE,
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

# "Markets" that are shops. Google files Rome's "Mercatino dell'Usato" second-hand chain under
# flea_market, usually along with shop types, and some supermarkets under market. Markets that
# are also tourist attractions (the Grand Bazaar) always stay.
SHOP_TYPES = {"store", "supermarket", "grocery_store", "car_repair", "service", "wholesaler", "manufacturer"}
SECOND_HAND_NAME = re.compile(r"\b(usato|used|second[- ]?hand|thrift|franchising|franchise)\b", re.IGNORECASE)

# Famous sights the popularity search missed (see add_famous_sights).
FAMOUS_MAX_LOOKUPS = 25  # Google searches per city
FAMOUS_MATCH_M = 500  # how far Google's place may lie from Wikidata's point
FAMOUS_SAME_SPOT_M = 75  # a sight we have this close covers it (the obelisk in Place de la Concorde)

RawResult = dict[str, Any]  # {"source": <search that found it>, "place": <Places API place dict>}


def fetch_raw(client: PlacesClient, city: CityConfig, max_nearby: int | None = None) -> tuple[list[RawResult], bool]:
    """The city's raw search results, and whether the search finished within `max_nearby`."""
    results, complete = fetch_adaptive(client, city, max_nearby)
    for query in TEXT_SEARCHES:
        results += [{"source": f"text:{query}", "place": p} for p in client.search_text(query, city.bounds)]
    return results, complete


def fetch_adaptive(
    client: PlacesClient, city: CityConfig, max_nearby: int | None = None
) -> tuple[list[RawResult], bool]:
    """Nearby Search on a quadtree, asking for every type at once in each cell.

    Google returns at most 20 places per request, most popular first. The search starts with one
    cell over the whole area; a cell whose 20 results are all popular enough to be among the
    city's ADAPTIVE_TOP_N best found so far may hide more such places, so it is split in four.
    A cell whose 20th result falls short can't: anything it didn't return is less popular still.
    Bigger cells go first, so the bar rises quickly and prunes most small cells. `max_nearby`
    caps the number of requests (the budget); the result says whether the search got to finish.
    """
    b = city.bounds
    lat0, lng0 = (b.south + b.north) / 2, (b.west + b.east) / 2
    width_km = (b.east - b.west) * KM_PER_DEG_LAT * math.cos(math.radians(lat0))
    half_km = max(width_km, (b.north - b.south) * KM_PER_DEG_LAT) / 2  # a square over the whole area
    queue = [(-half_km, 0, lat0, lng0, math.inf)]  # (-cell size, tie-breaker, centre, parent's 20th)
    order = 1
    kept_reviews: dict[str, int] = {}
    results: list[RawResult] = []
    requests = 0

    def bar() -> int:
        """Reviews a place needs to be among the top N found so far (at least MIN_RATING_COUNT)."""
        if len(kept_reviews) < ADAPTIVE_TOP_N:
            return MIN_RATING_COUNT
        return max(MIN_RATING_COUNT, heapq.nlargest(ADAPTIVE_TOP_N, kept_reviews.values())[-1])

    while queue and (max_nearby is None or requests < max_nearby):
        neg_half, _, lat, lng, parent_last = heapq.heappop(queue)
        if parent_last < bar():
            continue  # the parent's 20th result was already below the bar
        half = -neg_half
        places = client.search_nearby(LatLng(lat, lng), half * math.sqrt(2) * 1000, ADAPTIVE_TYPES)
        requests += 1
        results += [{"source": f"adaptive:{half * 2:.1f}km", "place": p} for p in places]
        for p in places:
            if categorize(p) is not None and p.get("userRatingCount", 0) >= MIN_RATING_COUNT:
                kept_reviews[p["id"]] = p["userRatingCount"]
        last = places[-1].get("userRatingCount", 0) if len(places) == MAX_NEARBY_RESULTS else -1
        if last >= bar() and half * 2 > MIN_CELL_KM:
            dlat = half / 2 / KM_PER_DEG_LAT
            dlng = half / 2 / (KM_PER_DEG_LAT * math.cos(math.radians(lat)))
            for sy in (-1, 1):
                for sx in (-1, 1):
                    heapq.heappush(queue, (-half / 2, order, lat + sy * dlat, lng + sx * dlng, last))
                    order += 1
    complete = not any(parent_last >= bar() for *_, parent_last in queue)
    print(f"  adaptive: {requests} Nearby requests, {len(kept_reviews)} places with {MIN_RATING_COUNT}+ reviews")
    return results, complete


def catalog_config(client: PlacesClient, city: CatalogCity) -> CityConfig:
    """A catalog city's search area: a square around the centre Google gives for its name."""
    place_id = client.find_place_id(city.query)
    if place_id is None:
        raise PlacesAPIError(404, f"no place found for {city.query!r}")
    centre = client.place_location(place_id)
    dlat = ADAPTIVE_RADIUS_KM / KM_PER_DEG_LAT
    dlng = ADAPTIVE_RADIUS_KM / (KM_PER_DEG_LAT * math.cos(math.radians(centre.lat)))
    bounds = BoundingBox(centre.lat - dlat, centre.lng - dlng, centre.lat + dlat, centre.lng + dlng)
    return catalog_city_config(city, bounds)


def catalog_city_config(city: CatalogCity, bounds: BoundingBox) -> CityConfig:
    return CityConfig(
        city.id, city.name_en, city.currency, city.timezone, bounds, name_tr=city.name_tr, country_code=city.country
    )


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
    google_type = place.get("primaryType")
    sight = SIGHTS.get(place["id"])  # hand-checked values win over the rules
    reviews = place.get("userRatingCount")
    return {
        "id": new_id(),
        "city_id": city_id,
        "place_id": place["id"],
        "name": place["displayName"]["text"],
        "category": category.value,
        "google_type": google_type,
        "latitude": place["location"]["latitude"],
        "longitude": place["location"]["longitude"],
        "avg_duration_min": (sight and sight.visit_minutes) or estimate_visit_minutes(google_type, category, reviews),
        "entry_price": sight.entry_price
        if sight and sight.entry_price is not None
        else estimate_entry_price(google_type),
        "opening_hours": json.dumps(periods) if periods else None,
        "rating": place.get("rating"),
        "user_rating_count": place.get("userRatingCount"),
    }


def is_shop(place: dict[str, Any]) -> bool:
    """Whether a "market" is really a shop (see SHOP_TYPES)."""
    types = set(place.get("types", []))
    if "tourist_attraction" in types:
        return False
    if types & SHOP_TYPES or any(t.endswith("_store") for t in types):
        return True
    return bool(SECOND_HAND_NAME.search(place["displayName"]["text"]))


def build_rows(raw: list[RawResult], city: CityConfig) -> list[dict[str, Any]]:
    """Deduplicate on place_id, filter, categorize and convert to DB rows."""
    rows_by_place_id: dict[str, dict[str, Any]] = {}
    for item in raw:
        place = item["place"]
        if place["id"] in rows_by_place_id or not is_relevant(place, city.bounds):
            continue
        if (sight := SIGHTS.get(place["id"])) and sight.same_as:
            continue  # part of another sight, e.g. the Louvre Pyramid
        category = categorize(place)
        if category is None or (category is POICategory.MARKET and is_shop(place)):
            continue
        rows_by_place_id[place["id"]] = to_row(place, city.id, category)
    words = city_words(city.id, city.name, city.name_tr)
    return drop_same_spot(list(rows_by_place_id.values()), words) + curated_rows(city)


def drop_same_spot(rows: list[dict[str, Any]], city_words: frozenset[str] = frozenset()) -> list[dict[str, Any]]:
    """Keep one listing per place. A row of one category at the same spot (SAME_SPOT_KM) as a more
    reviewed one is its second listing if it has a tiny share of its reviews or a word of its name
    (other than the city's, `city_words`): Google lists the Spice Bazaar as "Egyptian Bazaar" and
    "Mercado egipcio". Neighbours of comparable fame stay (the Propylaea, the Temple of Athena Nike)."""
    kept: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda r: -(r["user_rating_count"] or 0)):
        here = LatLng(row["latitude"], row["longitude"])
        reviews = row["user_rating_count"] or 0
        words = distinctive_words(row["name"]) - city_words
        if any(
            other["category"] == row["category"]
            and haversine_km(here, LatLng(other["latitude"], other["longitude"])) < SAME_SPOT_KM
            and (
                reviews <= SECOND_LISTING_SHARE * (other["user_rating_count"] or 0)
                or words & distinctive_words(other["name"])
            )
            for other in kept
        ):
            continue
        kept.append(row)
    return kept


def city_words(*names: str | None) -> frozenset[str]:
    """The words of a city's names, which many place names contain ("Amsterdam Tulip Museum")."""
    return frozenset(distinctive_words(" ".join(n for n in names if n)))


def find_famous_sights(
    client: PlacesClient, wiki: WikiClient, city_id: str, bounds: BoundingBox, rows: list[dict[str, Any]]
) -> list[RawResult]:
    """Famous sights the popularity search missed, looked up on Google by name.

    The search ranks places by Google's review count, which can be far too low for a famous
    sight with split listings (the British Museum showed 3,000 reviews). So the sights with the
    most Wikipedia articles around the city are checked against `rows`; each one that no row
    covers (one next to it, or one nearby with its name) is searched for by name, at most
    FAMOUS_MAX_LOOKUPS per city (Text Search: about $35 per 1,000, the first 1,000 a month free).
    The result must be near the sight and pass the usual filters. Returned as raw results, so
    they are cached and rebuilt like the search's own.
    """
    centre = LatLng((bounds.south + bounds.north) / 2, (bounds.west + bounds.east) / 2)
    radius_km = haversine_km(centre, LatLng(bounds.north, bounds.east))
    known_ids = {row["place_id"] for row in rows}
    have = list(rows)
    found: list[RawResult] = []
    lookups = 0
    for famous in wiki.famous_places(centre, radius_km):
        if lookups >= FAMOUS_MAX_LOOKUPS:
            break
        if not (bounds.south <= famous.where.lat <= bounds.north and bounds.west <= famous.where.lng <= bounds.east):
            continue
        if _covered(famous.label, famous.where, have):
            continue
        lookups += 1
        place = client.find_place_near(famous.label, famous.where, FAMOUS_MATCH_M)
        if place is None or place["id"] in known_ids or not is_relevant(place, bounds):
            continue
        category = categorize(place)
        if category is None or (category is POICategory.MARKET and is_shop(place)):
            continue
        found_at = LatLng(place["location"]["latitude"], place["location"]["longitude"])
        reach_m = FAMOUS_MATCH_M * (3 if category is POICategory.PARK else 1)  # parks are big
        if haversine_km(found_at, famous.where) * 1000 > reach_m:
            continue  # Google found something else of that name
        found.append({"source": f"famous:{famous.qid}", "place": place})
        have.append(to_row(place, city_id, category))
        known_ids.add(place["id"])
    names = ", ".join(item["place"]["displayName"]["text"] for item in found) or "-"
    print(f"  famous sights: {lookups} looked up on Google, added {len(found)}: {names}")
    return found


def _covered(label: str, where: LatLng, rows: list[dict[str, Any]]) -> bool:
    """Whether a row stands for this sight: one right next to it, or one nearby with its name."""
    for row in rows:
        km = haversine_km(where, LatLng(row["latitude"], row["longitude"]))
        if km * 1000 < FAMOUS_SAME_SPOT_M or (km * 1000 < FAMOUS_MATCH_M and name_score(row["name"], label) >= 0.75):
            return True
    return False


def curated_rows(city: CityConfig) -> list[dict[str, Any]]:
    return [
        {
            "id": new_id(),
            "city_id": city.id,
            "place_id": f"curated:{city.id}:{poi.slug}",  # not a Google ID; keeps upserts idempotent
            "name": poi.name,
            "category": poi.category.value,
            "google_type": None,
            "latitude": poi.lat,
            "longitude": poi.lng,
            "avg_duration_min": poi.avg_duration_min,
            "entry_price": Decimal(0),  # streets and districts: free to walk around
            "opening_hours": None,  # open-air, always accessible
            "rating": None,
            "user_rating_count": None,
        }
        for poi in CURATED_POIS.get(city.id, [])
    ]


def save_city(city: CityConfig, rows: list[dict[str, Any]], requests: int | None = None) -> int:
    """Upsert the city and its POIs; return how many stale POIs were removed."""
    with SessionLocal() as db:
        prices = CITY_PRICES.get(city.id)
        city_stmt = pg_insert(City).values(
            id=city.id,
            name=city.name,
            name_tr=city.name_tr,
            country_code=city.country_code,
            currency_code=city.currency_code,
            timezone=city.timezone,
            price_basis=prices.basis if prices else None,
            prices_checked_on=prices.checked_on if prices else None,
            refreshed_at=func.now(),
            last_ingest_requests=requests,
        )
        city_columns = (
            "name",
            "name_tr",
            "country_code",
            "currency_code",
            "timezone",
            "price_basis",
            "prices_checked_on",
            "refreshed_at",
            "last_ingest_requests",
        )
        db.execute(
            city_stmt.on_conflict_do_update(
                index_elements=[City.id],
                set_={col: city_stmt.excluded[col] for col in city_columns},
            )
        )
        if rows:
            poi_stmt = pg_insert(POI).values(rows)
            # Refresh everything but the id (saved routes point at it). Hand-tuned visit times
            # and prices live in scripts/sight_details.py, so they are refreshed too.
            refreshed = [
                "name",
                "category",
                "google_type",
                "latitude",
                "longitude",
                "avg_duration_min",
                "entry_price",
                "opening_hours",
                "rating",
                "user_rating_count",
            ]
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


def pick_for_refresh(
    cities: list[tuple[str, datetime | None, int | None]], budget: int, now: datetime | None = None
) -> list[str]:
    """Cities to refresh this run: the stalest first (never-refreshed ones before all), for as
    long as their expected cost (the last run's request count) fits in the budget. Cities
    refreshed in the last REFRESH_MIN_AGE_DAYS are left alone."""
    cutoff = (now or datetime.now(UTC)) - timedelta(days=REFRESH_MIN_AGE_DAYS)
    due = [c for c in cities if c[1] is None or c[1] < cutoff]
    oldest_first = sorted(due, key=lambda c: (c[1] is not None, c[1] or cutoff))
    picked: list[str] = []
    for city_id, _, last_requests in oldest_first:
        cost = last_requests or EXPECTED_CITY_REQUESTS
        if cost > budget:
            break  # it stays first in line for the next run
        picked.append(city_id)
        budget -= cost
    return picked


def refresh_candidates() -> list[tuple[str, datetime | None, int | None]]:
    """Cities already in the database that this script knows how to search."""
    known = set(CITIES) | {c.id for c in CATALOG}
    with SessionLocal() as db:
        rows = db.execute(select(City.id, City.refreshed_at, City.last_ingest_requests)).all()
    return [(r.id, r.refreshed_at, r.last_ingest_requests) for r in rows if r.id in known]


def repair_city(client: PlacesClient, wiki: WikiClient, city_id: str, dry_run: bool = False) -> None:
    """Bring a city already in the database up to the current rules without a new Nearby search:
    drop second-hand shops (by name, as shop types aren't stored) and second listings at the same
    spot, and add the famous sights the popularity search missed."""
    with SessionLocal() as db:
        pois = list(db.scalars(select(POI).where(POI.city_id == city_id)))
        rows = [
            {
                "place_id": p.place_id,
                "name": p.name,
                "category": p.category,
                "latitude": p.latitude,
                "longitude": p.longitude,
                "user_rating_count": p.user_rating_count,
            }
            for p in pois
        ]
        google = [r for r in rows if not r["place_id"].startswith("curated:")]
        city = db.get(City, city_id)
        words = city_words(city_id, city.name if city else None, city.name_tr if city else None)
        single = {r["place_id"] for r in drop_same_spot(google, words)}
        unwanted = {
            r["place_id"]: r["name"]
            for r in google
            if r["place_id"] not in single
            or (r["category"] == POICategory.MARKET.value and SECOND_HAND_NAME.search(r["name"]))
        }
        print(f"  dropping {len(unwanted)}: {', '.join(unwanted.values()) or '-'}")
        bounds = CITIES[city_id].bounds if city_id in CITIES else _extent(rows, pad_km=1.0)
        famous = find_famous_sights(client, wiki, city_id, bounds, [r for r in rows if r["place_id"] not in unwanted])
        if dry_run:
            return
        if unwanted:
            # Places on a saved route stay: the route points at them.
            db.execute(delete(POI).where(POI.place_id.in_(list(unwanted)), ~POI.route_stops.any()))
        if famous:
            new_rows = [to_row(item["place"], city_id, categorize(item["place"])) for item in famous]
            db.execute(pg_insert(POI).values(new_rows).on_conflict_do_nothing(index_elements=[POI.place_id]))
        db.commit()
    describe_new_places(city_id)


def _extent(rows: list[dict[str, Any]], pad_km: float) -> BoundingBox:
    """The box around the rows, widened by `pad_km` on every side."""
    lats = [r["latitude"] for r in rows]
    lngs = [r["longitude"] for r in rows]
    dlat = pad_km / KM_PER_DEG_LAT
    dlng = pad_km / (KM_PER_DEG_LAT * math.cos(math.radians(sum(lats) / len(lats))))
    return BoundingBox(min(lats) - dlat, min(lngs) - dlng, max(lats) + dlat, max(lngs) + dlng)


def print_summary(rows: list[dict[str, Any]]) -> None:
    counts = Counter(row["category"] for row in rows)
    print(f"  kept {len(rows)}: " + "  ".join(f"{cat}={n}" for cat, n in sorted(counts.items())))
    for category in sorted(counts):
        top = sorted((r for r in rows if r["category"] == category), key=lambda r: -(r["user_rating_count"] or 0))[:8]
        print(f"    {category:15} " + ", ".join(r["name"] for r in top))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    catalog = {c.id: c for c in CATALOG if c.id not in CITIES}
    parser.add_argument(
        "--city", action="append", choices=sorted({*CITIES, *catalog}), help="city to ingest (repeatable)"
    )
    parser.add_argument("--dry-run", action="store_true", help="fetch and summarize without writing to the DB")
    parser.add_argument("--use-cache", action="store_true", help="reuse cached raw results instead of calling the API")
    parser.add_argument("--max-requests", type=int, help="stop searching once this many Nearby requests are made")
    parser.add_argument(
        "--refresh", action="store_true", help="refresh the stalest cities in the database that fit --max-requests"
    )
    parser.add_argument(
        "--repair",
        action="store_true",
        help="for cities already in the database: drop second-hand shops and second listings, add famous sights "
        "the search missed (no Nearby search)",
    )
    args = parser.parse_args()
    sys.stdout.reconfigure(errors="replace")  # place names in any script, on any console
    api_key = get_settings().google_places_api_key

    if args.repair:
        if not api_key:
            sys.exit("GOOGLE_PLACES_API_KEY is not set in .env")
        with PlacesClient(api_key) as client, WikiClient() as wiki:
            if args.city:
                city_ids = args.city
            else:
                with SessionLocal() as db:
                    city_ids = list(db.scalars(select(City.id).order_by(City.id)))
            for city_id in city_ids:
                print(f"== {city_id}")
                try:
                    repair_city(client, wiki, city_id, dry_run=args.dry_run)
                except WikiError as e:  # Wikidata is down: the other cities can still be repaired
                    print(f"  skipped, Wikidata didn't answer: {e}")
            print("requests:", dict(client.requests))
        return

    if args.refresh:
        if args.max_requests is None:
            sys.exit("--refresh needs --max-requests (the budget)")
        city_ids = pick_for_refresh(refresh_candidates(), args.max_requests)
        print(f"refreshing {len(city_ids)} cities: {', '.join(city_ids) or '-'}")
    else:
        city_ids = args.city or list(CITIES)
    if not args.use_cache and not api_key:
        sys.exit("GOOGLE_PLACES_API_KEY is not set in .env")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with PlacesClient(api_key or "") as client, WikiClient() as wiki:
        for city_id in city_ids:
            cache_file = CACHE_DIR / f"{city_id}.json"
            requests = None
            if args.use_cache:
                cached = json.loads(cache_file.read_text(encoding="utf-8"))
                # Newer caches store the search area along with the results (older ones are a
                # plain list). Names, currency etc. always come from the current code.
                raw = cached["raw"] if isinstance(cached, dict) else cached
                if city_id in CITIES:
                    city = CITIES[city_id]
                else:
                    city = catalog_city_config(catalog[city_id], BoundingBox(**cached["city"]["bounds"]))
                print(f"== {city.name}\n  loaded {len(raw)} raw results from {cache_file.name}")
            else:
                city = CITIES.get(city_id) or catalog_config(client, catalog[city_id])
                print(f"== {city.name}")
                before = client.requests["nearby"]
                budget = None if args.max_requests is None else args.max_requests - before
                raw, complete = fetch_raw(client, city, max_nearby=budget)
                requests = client.requests["nearby"] - before
                if not complete:
                    # Saving half a city would delete the places the search didn't get to.
                    print("  the request budget ran out before the search finished: not saved")
                    break
                try:
                    raw += find_famous_sights(client, wiki, city.id, city.bounds, build_rows(raw, city))
                except WikiError as e:
                    print(f"  famous sights skipped, Wikidata didn't answer: {e}")
                cache_file.write_text(
                    json.dumps({"city": asdict(city), "raw": raw}, ensure_ascii=False), encoding="utf-8"
                )

            rows = build_rows(raw, city)
            print_summary(rows)
            if not args.dry_run:
                removed = save_city(city, rows, requests)
                print(f"  saved {len(rows)} POIs, removed {removed} stale")
                describe_new_places(city.id)
    print("requests:", dict(client.requests))


if __name__ == "__main__":
    main()

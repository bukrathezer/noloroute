import math
from collections import Counter
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

import scripts.ingest_places as ingest
from app.services.geo import LatLng, haversine_km
from app.services.places_client import BoundingBox
from scripts.city_catalog import CATALOG
from scripts.ingest_places import CityConfig, catalog_config, fetch_adaptive, pick_for_refresh

KM_PER_DEG_LAT = 111.32
CENTRE = LatLng(41.9, 12.5)


def place(i: int, lat: float, lng: float, reviews: int, primary_type: str = "museum") -> dict:
    return {
        "id": f"p{i}",
        "displayName": {"text": f"Place {i}"},
        "location": {"latitude": lat, "longitude": lng},
        "types": [primary_type],
        "primaryType": primary_type,
        "userRatingCount": reviews,
        "businessStatus": "OPERATIONAL",
    }


class FakePlaces:
    """Nearby Search over a fixed set of places: the 20 most reviewed inside the circle."""

    def __init__(self, places: list[dict]) -> None:
        self.places = places
        self.requests: Counter[str] = Counter()
        self.circles: list[tuple[LatLng, float]] = []

    def search_nearby(self, center: LatLng, radius_m: float, included_types: list[str]) -> list[dict]:
        self.requests["nearby"] += 1
        self.circles.append((center, radius_m))
        inside = [
            p
            for p in self.places
            if haversine_km(center, LatLng(p["location"]["latitude"], p["location"]["longitude"])) * 1000 <= radius_m
        ]
        return sorted(inside, key=lambda p: -p["userRatingCount"])[:20]

    def search_text(self, query: str, bounds: BoundingBox):
        return iter(())

    def find_place_id(self, query: str) -> str:
        self.requests["text_ids"] += 1
        return "city-place-id"

    def place_location(self, place_id: str) -> LatLng:
        self.requests["details"] += 1
        return CENTRE


def square(half_km: float, centre: LatLng = CENTRE, wide: float = 1.0) -> CityConfig:
    dlat = half_km / KM_PER_DEG_LAT
    dlng = half_km * wide / (KM_PER_DEG_LAT * math.cos(math.radians(centre.lat)))
    bounds = BoundingBox(centre.lat - dlat, centre.lng - dlng, centre.lat + dlat, centre.lng + dlng)
    return CityConfig("rome", "Rome", "EUR", "Europe/Rome", bounds)


def scattered(n: int, spread_km: float, reviews: int, start: int = 0, centre: LatLng = CENTRE) -> list[dict]:
    """n places spread over a square `spread_km` wide around `centre`, each with `reviews` reviews."""
    side = math.ceil(math.sqrt(n))
    step = spread_km / side
    out = []
    for i in range(n):
        dx, dy = (i % side + 0.5) * step - spread_km / 2, (i // side + 0.5) * step - spread_km / 2
        lat = centre.lat + dy / KM_PER_DEG_LAT
        lng = centre.lng + dx / (KM_PER_DEG_LAT * math.cos(math.radians(centre.lat)))
        out.append(place(start + i, lat, lng, reviews))
    return out


def test_a_quiet_city_takes_a_single_request() -> None:
    client = FakePlaces(scattered(12, spread_km=6, reviews=5_000))
    results, complete = fetch_adaptive(client, square(10))
    assert client.requests["nearby"] == 1 and complete
    assert len({r["place"]["id"] for r in results}) == 12


def test_a_full_cell_of_popular_places_is_split_until_everything_is_found() -> None:
    client = FakePlaces(scattered(60, spread_km=8, reviews=5_000))
    results, complete = fetch_adaptive(client, square(10))
    assert complete
    assert client.requests["nearby"] > 1
    assert {r["place"]["id"] for r in results} == {f"p{i}" for i in range(60)}


def test_cells_whose_20th_place_is_too_obscure_are_not_split() -> None:
    # 20 popular places and many obscure ones (below the review minimum) all around.
    popular = scattered(20, spread_km=4, reviews=10_000)
    obscure = scattered(80, spread_km=8, reviews=50, start=100)
    client = FakePlaces(popular + obscure)
    fetch_adaptive(client, square(10))
    assert client.requests["nearby"] <= 5  # the root, then one round of splits at most


def test_once_the_top_is_known_less_popular_cells_are_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ingest, "ADAPTIVE_TOP_N", 20)
    stars = scattered(30, spread_km=2, reviews=50_000)  # the city's top sights, in the centre
    others = scattered(200, spread_km=16, reviews=1_000, start=100)
    client = FakePlaces(stars + others)
    results, complete = fetch_adaptive(client, square(10))
    found = {r["place"]["id"] for r in results}
    assert complete and {f"p{i}" for i in range(30)} <= found
    unlimited = FakePlaces(stars + others)
    monkeypatch.setattr(ingest, "ADAPTIVE_TOP_N", 10_000)
    fetch_adaptive(unlimited, square(10))
    assert client.requests["nearby"] < unlimited.requests["nearby"]


def test_the_budget_stops_the_search_and_says_so() -> None:
    client = FakePlaces(scattered(200, spread_km=8, reviews=5_000))
    _, complete = fetch_adaptive(client, square(10), max_nearby=3)
    assert client.requests["nearby"] == 3 and not complete


def test_a_wide_area_is_searched_edge_to_edge() -> None:
    east = LatLng(CENTRE.lat, CENTRE.lng + 18 / (KM_PER_DEG_LAT * math.cos(math.radians(CENTRE.lat))))
    client = FakePlaces([place(1, east.lat, east.lng, 5_000)])
    results, _ = fetch_adaptive(client, square(5, wide=4.0))  # 10 km tall, 40 km wide
    assert [r["place"]["id"] for r in results] == ["p1"]


def test_a_catalog_city_is_searched_around_its_centre() -> None:
    client = FakePlaces([])
    rome = next(c for c in CATALOG if c.id == "rome")
    city = catalog_config(client, rome)
    b = city.bounds
    assert ((b.south + b.north) / 2, (b.west + b.east) / 2) == pytest.approx((CENTRE.lat, CENTRE.lng))
    assert (b.north - b.south) * KM_PER_DEG_LAT == pytest.approx(2 * ingest.ADAPTIVE_RADIUS_KM)
    assert (city.name, city.name_tr, city.country_code, city.currency_code) == ("Rome", "Roma", "IT", "EUR")
    assert client.requests == Counter({"text_ids": 1, "details": 1})


# --- the monthly refresh ------------------------------------------------------------------------


def test_refresh_takes_the_stalest_cities_that_fit_the_budget() -> None:
    cities = [
        ("fresh", datetime(2026, 9, 20, tzinfo=UTC), 50),
        ("old", datetime(2026, 7, 1, tzinfo=UTC), 60),
        ("new", None, None),  # never refreshed: first, at the default cost
        ("older", datetime(2026, 6, 1, tzinfo=UTC), 70),
    ]
    now = datetime(2026, 10, 2, tzinfo=UTC)
    assert pick_for_refresh(cities, budget=240, now=now) == ["new", "older", "old"]
    # The next one in line doesn't fit: stop rather than skip it, so it goes first next time.
    assert pick_for_refresh(cities, budget=200, now=now) == ["new", "older"]


def test_refresh_leaves_recently_refreshed_cities_alone() -> None:
    now = datetime(2026, 10, 2, tzinfo=UTC)
    cities = [
        ("yesterday", datetime(2026, 10, 1, tzinfo=UTC), 50),
        ("last-month", datetime(2026, 9, 1, tzinfo=UTC), 50),
    ]
    assert pick_for_refresh(cities, budget=900, now=now) == ["last-month"]


# --- the catalog ----------------------------------------------------------------------------------


def test_catalog_entries_are_well_formed() -> None:
    ids = [c.id for c in CATALOG]
    assert len(ids) == len(set(ids))
    for city in CATALOG:
        ZoneInfo(city.timezone)
        assert len(city.country) == 2 and city.country.isupper(), city.id
        assert len(city.currency) == 3 and city.currency.isupper(), city.id
        assert city.name_en and city.name_tr and city.query, city.id

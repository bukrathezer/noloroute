import asyncio
from collections.abc import Iterator
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api.v1.routes_places import get_place_search_client
from app.api.v1.routes_suggestions import FOOD_LOOKUPS_PER_IP
from app.main import app
from app.services.food import PER_ANCHOR, Stop, food_suggestions, pick_anchors, to_food_place
from app.services.geo import LatLng
from app.services.place_search import PlaceSearchError

KM_LAT = 1 / 111.32
TUESDAY = date(2026, 10, 6)
# Open for dinner only: 18:00-23:00 every day.
DINNER_ONLY = [{"open": {"day": d, "hour": 18}, "close": {"day": d, "hour": 23}} for d in range(7)]


def stop(name: str, north_km: float) -> Stop:
    return Stop(name, LatLng(41.0 + north_km * KM_LAT, 29.0))


def restaurant(i: int, north_km: float, rating: float = 4.6, reviews: int = 5_000, **extra) -> dict:
    return {
        "id": f"r{i}",
        "displayName": {"text": f"Restaurant {i}"},
        "location": {"latitude": 41.0 + north_km * KM_LAT, "longitude": 29.0},
        "primaryTypeDisplayName": {"text": "Turkish restaurant"},
        "rating": rating,
        "userRatingCount": reviews,
        "priceLevel": "PRICE_LEVEL_MODERATE",
        "googleMapsUri": f"https://maps.google.com/?cid={i}",
        **extra,
    }


class FakePlaceSearch:
    """Returns the given restaurants that are within the circle."""

    def __init__(self, places: list[dict], fail: bool = False) -> None:
        self.places = places
        self.fail = fail
        self.calls: list[LatLng] = []

    async def search_nearby(self, center, radius_m, included_types, field_mask, language, excluded_primary_types=None):
        self.calls.append(center)
        if self.fail:
            raise PlaceSearchError("down")
        return [p for p in self.places if abs(p["location"]["latitude"] - center.lat) / KM_LAT * 1000 <= radius_m]


# --- where to look -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("n", "expected"),
    [(1, ["s0"]), (2, ["s0", "s1"]), (3, ["s0", "s2"]), (6, ["s1", "s4"]), (7, ["s2", "s4"])],
)
def test_anchors_spread_along_the_day(n: int, expected: list[str]) -> None:
    stops = [stop(f"s{i}", i) for i in range(n)]
    assert [s.name for s in pick_anchors(stops)] == expected


# --- which places ----------------------------------------------------------------------------------


def test_only_well_rated_popular_open_places_are_suggested() -> None:
    assert to_food_place(restaurant(1, 0), None) is not None
    assert to_food_place(restaurant(2, 0, rating=3.9), None) is None
    assert to_food_place(restaurant(3, 0, reviews=50), None) is None
    assert to_food_place(restaurant(4, 0, businessStatus="CLOSED_TEMPORARILY"), None) is None
    # Dinner only: still fine (a meal fits), and that day's hours are shown.
    dinner = to_food_place(restaurant(5, 0, regularOpeningHours={"periods": DINNER_ONLY}), TUESDAY)
    assert dinner is not None and dinner.hours == "18:00–23:00"
    breakfast_only = [{"open": {"day": d, "hour": 7}, "close": {"day": d, "hour": 11}} for d in range(7)]
    assert to_food_place(restaurant(6, 0, regularOpeningHours={"periods": breakfast_only}), TUESDAY) is None


def test_fields_are_read_from_the_places_response() -> None:
    food = to_food_place(restaurant(1, 0), None)
    assert food is not None
    assert (food.name, food.cuisine, food.price_level, food.maps_url) == (
        "Restaurant 1",
        "Turkish restaurant",
        2,
        "https://maps.google.com/?cid=1",
    )


def test_suggestions_are_grouped_by_nearest_stop_best_first() -> None:
    stops = [stop("Hagia Sophia", 0), stop("Topkapi", 0.5), stop("Galata", 3.0)]  # anchors: first and last
    places = [
        restaurant(1, 0.1, reviews=2_000),
        restaurant(2, -0.2, reviews=20_000),
        restaurant(3, 3.2, reviews=8_000),
        restaurant(4, 0.1, rating=3.5),  # badly rated
        *[restaurant(10 + i, 2.9, reviews=1_000 + i) for i in range(6)],  # more than PER_ANCHOR near Galata
    ]
    client = FakePlaceSearch(places)
    groups = asyncio.run(food_suggestions(client, stops, None, "en"))
    assert len(client.calls) == 2
    assert [g.near for g in groups] == ["Hagia Sophia", "Galata"]
    assert [p.place_id for p in groups[0].places] == ["r2", "r1"]
    assert len(groups[1].places) == PER_ANCHOR and groups[1].places[0].place_id == "r3"
    assert groups[0].places[0].distance_m == pytest.approx(200, abs=5)


def test_a_chain_shows_up_once_with_its_best_branch() -> None:
    branches = [
        restaurant(1, 0.1, reviews=40_000, displayName={"text": "Hafız Mustafa 1864 Sirkeci"}),
        restaurant(2, 0.2, reviews=18_000, displayName={"text": "Hafız Mustafa 1864 Eminönü"}),
        restaurant(3, 0.3, reviews=9_000),
    ]
    [group] = asyncio.run(food_suggestions(FakePlaceSearch(branches), [stop("Hagia Sophia", 0)], None, "tr"))
    assert [p.place_id for p in group.places] == ["r1", "r3"]


# --- the API ------------------------------------------------------------------------------------------


@pytest.fixture
def api() -> Iterator[tuple[TestClient, FakePlaceSearch]]:
    fake = FakePlaceSearch([restaurant(1, 0.1), restaurant(2, 0.2, regularOpeningHours={"periods": DINNER_ONLY})])
    app.dependency_overrides[get_place_search_client] = lambda: fake
    try:
        with TestClient(app) as test_client:
            yield test_client, fake
    finally:
        app.dependency_overrides.clear()


def body(**extra) -> dict:
    return {"stops": [{"name": "Hagia Sophia", "lat": 41.0, "lng": 29.0}], "lang": "tr", **extra}


def test_food_endpoint_returns_places_by_stop(api) -> None:
    client, _ = api
    resp = client.post("/api/v1/suggestions/food", json=body(date=TUESDAY.isoformat()))
    assert resp.status_code == 200, resp.text
    [group] = resp.json()
    assert group["near"] == "Hagia Sophia"
    assert [p["place_id"] for p in group["places"]] == ["r1", "r2"]
    assert group["places"][1]["hours"] == "18:00–23:00"


def test_food_endpoint_validates_input(api) -> None:
    client, _ = api
    assert client.post("/api/v1/suggestions/food", json={"stops": [], "lang": "tr"}).status_code == 422
    assert client.post("/api/v1/suggestions/food", json=body(lang="de")).status_code == 422


def test_food_endpoint_reports_upstream_failures(api) -> None:
    client, fake = api
    fake.fail = True
    assert client.post("/api/v1/suggestions/food", json=body()).status_code == 502


def test_food_endpoint_is_rate_limited(api, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = api
    monkeypatch.setattr(FOOD_LOOKUPS_PER_IP, "limit", 2)
    codes = [client.post("/api/v1/suggestions/food", json=body()).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_food_endpoint_needs_an_api_key() -> None:
    app.dependency_overrides.clear()
    with TestClient(app) as client:
        client.app.state.place_search_client = None
        assert client.post("/api/v1/suggestions/food", json=body()).status_code == 503

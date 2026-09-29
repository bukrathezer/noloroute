import asyncio
from collections.abc import Iterator
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api.v1.routes_places import get_place_search_client
from app.api.v1.routes_suggestions import SUGGESTION_LOOKUPS_PER_IP
from app.main import app
from app.services.geo import LatLng
from app.services.place_search import PlaceSearchError
from app.services.suggestions import (
    FOOD,
    NIGHTLIFE,
    PER_ANCHOR,
    Anchor,
    food_anchors,
    nightlife_anchors,
    suggestions,
    to_suggestion,
)

KM_LAT = 1 / 111.32
TUESDAY = date(2026, 10, 6)
SATURDAY = date(2026, 10, 10)
HOTEL = LatLng(41.0, 29.0)
# Open for dinner only: 18:00-23:00 every day.
DINNER_ONLY = [{"open": {"day": d, "hour": 18}, "close": {"day": d, "hour": 23}} for d in range(7)]


def stop(name: str, north_km: float) -> Anchor:
    return Anchor(name, LatLng(41.0 + north_km * KM_LAT, 29.0))


def place(i: int, north_km: float, rating: float = 4.6, reviews: int = 5_000, **extra) -> dict:
    return {
        "id": f"r{i}",
        "displayName": {"text": f"Place {i}"},
        "location": {"latitude": 41.0 + north_km * KM_LAT, "longitude": 29.0},
        "primaryTypeDisplayName": {"text": "Turkish restaurant"},
        "rating": rating,
        "userRatingCount": reviews,
        "priceLevel": "PRICE_LEVEL_MODERATE",
        "googleMapsUri": f"https://maps.google.com/?cid={i}",
        **extra,
    }


def hours(open_hour: int, close_hour: int, days=range(7)) -> dict:
    """Open daily from open_hour to close_hour (a close_hour after 24 runs into the next day)."""
    return {
        "regularOpeningHours": {
            "periods": [
                {
                    "open": {"day": d, "hour": open_hour},
                    "close": {"day": (d + close_hour // 24) % 7, "hour": close_hour % 24},
                }
                for d in days
            ]
        }
    }


class FakePlaceSearch:
    """Returns the given places that are within the circle."""

    def __init__(self, places: list[dict], fail: bool = False) -> None:
        self.places = places
        self.fail = fail
        self.calls: list[tuple[LatLng, float, list[str]]] = []

    async def search_nearby(
        self,
        center,
        radius_m,
        included_types,
        field_mask,
        language,
        excluded_primary_types=None,
        primary_types_only=False,
    ):
        self.calls.append((center, radius_m, included_types, primary_types_only))
        if self.fail:
            raise PlaceSearchError("down")
        return [p for p in self.places if abs(p["location"]["latitude"] - center.lat) / KM_LAT * 1000 <= radius_m]


# --- where to look -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("n", "expected"),
    [(1, ["s0"]), (2, ["s0", "s1"]), (3, ["s0", "s2"]), (6, ["s1", "s4"]), (7, ["s2", "s4"])],
)
def test_food_anchors_spread_along_the_day(n: int, expected: list[str]) -> None:
    stops = [stop(f"s{i}", i) for i in range(n)]
    assert [s.name for s in food_anchors(stops)] == expected


def test_nightlife_looks_near_the_hotel_and_a_far_last_stop() -> None:
    near_end = [stop("a", 3), stop("b", 0.5)]
    far_end = [stop("a", 0.5), stop("b", 3)]
    assert [a.name for a in nightlife_anchors(HOTEL, near_end)] == [None]
    assert [a.name for a in nightlife_anchors(HOTEL, far_end)] == [None, "b"]
    assert [a.name for a in nightlife_anchors(HOTEL, [])] == [None]


# --- which places ----------------------------------------------------------------------------------


def test_only_well_rated_popular_open_places_are_suggested() -> None:
    assert to_suggestion(place(1, 0), FOOD, None) is not None
    assert to_suggestion(place(2, 0, rating=3.9), FOOD, None) is None
    assert to_suggestion(place(3, 0, reviews=50), FOOD, None) is None
    assert to_suggestion(place(4, 0, businessStatus="CLOSED_TEMPORARILY"), FOOD, None) is None
    # Dinner only: still fine (a meal fits), and that day's hours are shown.
    dinner = to_suggestion(place(5, 0, regularOpeningHours={"periods": DINNER_ONLY}), FOOD, TUESDAY)
    assert dinner is not None and dinner.hours == "18:00–23:00"
    assert to_suggestion(place(6, 0, **hours(7, 11)), FOOD, TUESDAY) is None  # breakfast only


def test_nightlife_must_be_open_in_the_evening() -> None:
    assert to_suggestion(place(1, 0, **hours(18, 26)), NIGHTLIFE, TUESDAY) is not None  # 18:00-02:00
    assert to_suggestion(place(2, 0, **hours(9, 17)), NIGHTLIFE, TUESDAY) is None  # a daytime cafe-bar
    # Saturday from 23:30 into Sunday: the hours after midnight count for Saturday night.
    late = {
        "regularOpeningHours": {
            "periods": [{"open": {"day": 6, "hour": 23, "minute": 30}, "close": {"day": 0, "hour": 5}}]
        }
    }
    assert to_suggestion(place(3, 0, **late), NIGHTLIFE, SATURDAY) is not None
    assert to_suggestion(place(4, 0, reviews=150), NIGHTLIFE, None) is not None  # a lower bar than for food


def test_fields_are_read_from_the_places_response() -> None:
    suggestion = to_suggestion(place(1, 0), FOOD, None)
    assert suggestion is not None
    assert (suggestion.name, suggestion.category, suggestion.price_level, suggestion.maps_url) == (
        "Place 1",
        "Turkish restaurant",
        2,
        "https://maps.google.com/?cid=1",
    )


def test_suggestions_are_grouped_by_nearest_anchor_best_first() -> None:
    anchors = food_anchors([stop("Hagia Sophia", 0), stop("Topkapi", 0.5), stop("Galata", 3.0)])  # first, last
    places = [
        place(1, 0.1, reviews=2_000),
        place(2, -0.2, reviews=20_000),
        place(3, 3.2, reviews=8_000),
        place(4, 0.1, rating=3.5),  # badly rated
        *[place(10 + i, 2.9, reviews=1_000 + i) for i in range(6)],  # more than PER_ANCHOR near Galata
    ]
    client = FakePlaceSearch(places)
    groups = asyncio.run(suggestions(client, anchors, FOOD, None, "en"))
    assert len(client.calls) == 2
    assert [g.near for g in groups] == ["Hagia Sophia", "Galata"]
    assert [p.place_id for p in groups[0].places] == ["r2", "r1"]
    assert len(groups[1].places) == PER_ANCHOR and groups[1].places[0].place_id == "r3"
    assert groups[0].places[0].distance_m == pytest.approx(200, abs=5)


def test_a_chain_shows_up_once_with_its_best_branch() -> None:
    branches = [
        place(1, 0.1, reviews=40_000, displayName={"text": "Hafız Mustafa 1864 Sirkeci"}),
        place(2, 0.2, reviews=18_000, displayName={"text": "Hafız Mustafa 1864 Eminönü"}),
        place(3, 0.3, reviews=9_000),
    ]
    [group] = asyncio.run(suggestions(FakePlaceSearch(branches), [stop("Hagia Sophia", 0)], FOOD, None, "tr"))
    assert [p.place_id for p in group.places] == ["r1", "r3"]


def test_nightlife_searches_its_own_types_near_the_hotel() -> None:
    client = FakePlaceSearch([place(1, 0.3, **hours(19, 26))])
    [group] = asyncio.run(suggestions(client, nightlife_anchors(HOTEL, []), NIGHTLIFE, TUESDAY, "en"))
    assert group.near is None  # the accommodation
    _, radius_m, types, primary_only = client.calls[0]
    assert radius_m == NIGHTLIFE.radius_m and "night_club" in types and "restaurant" not in types
    assert primary_only  # a restaurant with a bar is not nightlife


# --- the API ------------------------------------------------------------------------------------------


@pytest.fixture
def api() -> Iterator[tuple[TestClient, FakePlaceSearch]]:
    fake = FakePlaceSearch(
        [place(1, 0.1, **hours(12, 26)), place(2, 0.2, regularOpeningHours={"periods": DINNER_ONLY})]
    )
    app.dependency_overrides[get_place_search_client] = lambda: fake
    try:
        with TestClient(app) as test_client:
            yield test_client, fake
    finally:
        app.dependency_overrides.clear()


def food_body(**extra) -> dict:
    return {"stops": [{"name": "Hagia Sophia", "lat": 41.0, "lng": 29.0}], "lang": "tr", **extra}


def test_food_endpoint_returns_places_by_stop(api) -> None:
    client, _ = api
    resp = client.post("/api/v1/suggestions/food", json=food_body(date=TUESDAY.isoformat()))
    assert resp.status_code == 200, resp.text
    [group] = resp.json()
    assert group["near"] == "Hagia Sophia"
    assert [p["place_id"] for p in group["places"]] == ["r1", "r2"]
    assert group["places"][1]["hours"] == "18:00–23:00"


def test_nightlife_endpoint_lists_places_open_that_evening(api) -> None:
    client, fake = api
    fake.places = [place(1, 0.1, **hours(19, 26)), place(2, 0.2, **hours(9, 17))]  # a bar, a daytime cafe
    body = {"accommodation": {"lat": 41.0, "lng": 29.0}, "stops": [], "date": TUESDAY.isoformat(), "lang": "en"}
    resp = client.post("/api/v1/suggestions/nightlife", json=body)
    assert resp.status_code == 200, resp.text
    [group] = resp.json()
    assert group["near"] is None
    assert [p["place_id"] for p in group["places"]] == ["r1"]
    assert group["places"][0]["hours"] == "19:00–02:00"


def test_endpoints_validate_input(api) -> None:
    client, _ = api
    assert client.post("/api/v1/suggestions/food", json={"stops": [], "lang": "tr"}).status_code == 422
    assert client.post("/api/v1/suggestions/food", json=food_body(lang="de")).status_code == 422
    assert client.post("/api/v1/suggestions/nightlife", json={"stops": []}).status_code == 422  # no accommodation


def test_upstream_failures_are_reported(api) -> None:
    client, fake = api
    fake.fail = True
    assert client.post("/api/v1/suggestions/food", json=food_body()).status_code == 502


def test_food_and_nightlife_share_a_rate_limit(api, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = api
    monkeypatch.setattr(SUGGESTION_LOOKUPS_PER_IP, "limit", 2)
    night = {"accommodation": {"lat": 41.0, "lng": 29.0}}
    codes = [
        client.post("/api/v1/suggestions/food", json=food_body()).status_code,
        client.post("/api/v1/suggestions/nightlife", json=night).status_code,
        client.post("/api/v1/suggestions/food", json=food_body()).status_code,
    ]
    assert codes == [200, 200, 429]


def test_suggestions_need_an_api_key() -> None:
    app.dependency_overrides.clear()
    with TestClient(app) as client:
        client.app.state.place_search_client = None
        assert client.post("/api/v1/suggestions/food", json=food_body()).status_code == 503

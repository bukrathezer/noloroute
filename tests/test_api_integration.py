"""Endpoint tests against a real PostgreSQL database (skipped when none is reachable).

Each test runs inside a transaction that is rolled back afterwards (see conftest.py), so the
test data never persists and the local development database stays untouched.
"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from tests.seed import CITY_ID, HOTEL, POI_COUNT, PRICES_CHECKED_ON


def test_list_cities_includes_poi_count(client: TestClient) -> None:
    cities = {c["id"]: c for c in client.get("/api/v1/cities").json()}
    city = cities[CITY_ID]
    assert {k: city[k] for k in ("id", "name", "name_tr", "country_code", "currency_code", "poi_count")} == {
        "id": CITY_ID,
        "name": "Test City",
        "name_tr": "Test Şehri",
        "country_code": "FR",
        "currency_code": "EUR",
        "poi_count": POI_COUNT,
    }
    # The centre is the average POI position, which the seed data places around the hotel.
    assert city["center_lat"] == pytest.approx(HOTEL["lat"], abs=0.02)
    assert city["center_lng"] == pytest.approx(HOTEL["lng"], abs=0.02)


def test_plan_route(client: TestClient) -> None:
    resp = client.post("/api/v1/routes/plan", json={"city_id": CITY_ID, "accommodation": HOTEL, "duration_days": 2})
    assert resp.status_code == 200
    plan = resp.json()
    assert plan["currency_code"] == "EUR"
    # Which ticket the entry prices are, and when they were checked, come from the city.
    assert (plan["price_basis"], plan["prices_checked_on"]) == ("adult", PRICES_CHECKED_ON.isoformat())
    assert [d["day_number"] for d in plan["days"]] == [1, 2]
    assert all(d["dropped_stops"] == [] for d in plan["days"])
    assert all(d["stops"] and d["routing_source"] == "estimate" for d in plan["days"])

    stops = [s for d in plan["days"] for s in d["stops"]]
    assert len({s["poi_id"] for s in stops}) == len(stops)  # no POI visited twice
    priced = [s for s in stops if s["entry_price"] is not None]
    assert Decimal(plan["total_entry_cost"]) == sum(Decimal(s["entry_price"]) for s in priced)
    assert plan["unpriced_stop_count"] == len(stops) - len(priced)


def test_plan_route_respects_budget(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/routes/plan",
        json={"city_id": CITY_ID, "accommodation": HOTEL, "duration_days": 2, "budget": "25"},
    )
    assert resp.status_code == 200
    assert Decimal(resp.json()["total_entry_cost"]) <= 25


def test_plan_route_unknown_city(client: TestClient) -> None:
    resp = client.post("/api/v1/routes/plan", json={"city_id": "atlantis", "accommodation": HOTEL, "duration_days": 1})
    assert resp.status_code == 404


def test_plan_route_hotel_outside_city(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/routes/plan",
        json={"city_id": CITY_ID, "accommodation": {"lat": 41.0, "lng": 28.9}, "duration_days": 1},
    )
    assert resp.status_code == 422

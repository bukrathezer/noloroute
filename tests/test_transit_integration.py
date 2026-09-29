"""Transit plans through the API: planning, removing stops, saving, and the per-client limit
(rolled back after each test)."""

from datetime import UTC
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.v1.routes_route import TRANSIT_ROUTINGS_PER_IP, city_timezone, get_routes_client
from app.main import app
from app.models import City, SavedRoute
from tests.fake_routes import FakeTransitClient
from tests.seed import CITY_ID, HOTEL

PASSWORD = "s3cure-enough-password"


@pytest.fixture
def fake(client: TestClient) -> FakeTransitClient:
    """Google routing replaced by the fake (the `client` fixture clears the override afterwards).

    The seed city is small, so transit is offered from 0.5 km on."""
    fake = FakeTransitClient(transit_min_km=0.5)
    app.dependency_overrides[get_routes_client] = lambda: fake
    return fake


def plan(client: TestClient, mode: str = "TRANSIT", days: int = 2) -> dict[str, Any]:
    body = {"city_id": CITY_ID, "accommodation": HOTEL, "duration_days": days, "travel_mode": mode}
    resp = client.post("/api/v1/routes/plan", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def legs(day: dict[str, Any]) -> list[dict[str, Any] | None]:
    return [s["leg_from_previous"] for s in day["stops"]] + [day["return_leg"]]


def test_transit_plan_says_how_each_leg_is_travelled(client: TestClient, fake: FakeTransitClient) -> None:
    result = plan(client)
    assert result["travel_mode"] == "TRANSIT"
    for day in result["days"]:
        assert day["routing_source"] == "google" and day["transit_available"] is True
        assert all(leg is not None and leg["mode"] in ("WALK", "TRANSIT") for leg in legs(day))
    rides = [ride for day in result["days"] for leg in legs(day) if leg for ride in leg["rides"]]
    assert rides and rides[0]["line"] == "M1" and rides[0]["vehicle"] == "SUBWAY"
    # Two matrices (walking and transit) per day.
    assert sorted(mode for mode, _, _ in fake.matrix_calls) == ["TRANSIT", "TRANSIT", "WALK", "WALK"]


def test_removing_a_stop_reroutes_the_day_with_transit(client: TestClient, fake: FakeTransitClient) -> None:
    result = plan(client)
    day1, day2 = result["days"]
    removed = day1["stops"][0]["poi_id"]
    calls_before = len(fake.matrix_calls)

    resp = client.post("/api/v1/routes/plan/remove-stop", json={"plan": result, "poi_id": removed})
    assert resp.status_code == 200, resp.text
    new_day1, new_day2 = resp.json()["days"]
    assert removed not in [s["poi_id"] for s in new_day1["stops"]]
    assert all(leg is not None for leg in legs(new_day1))
    assert new_day2 == day2
    assert len(fake.matrix_calls) == calls_before + 2  # only the changed day


def test_a_saved_transit_plan_keeps_its_legs(client: TestClient, fake: FakeTransitClient) -> None:
    result = plan(client)
    token = client.post("/api/v1/auth/register", json={"email": "ada@example.com", "password": PASSWORD})
    headers = {"Authorization": f"Bearer {token.json()['access_token']}"}

    saved = client.post("/api/v1/routes", json={"plan": result}, headers=headers).json()
    reopened = client.get(f"/api/v1/routes/{saved['id']}", headers=headers).json()
    assert reopened["travel_mode"] == "TRANSIT"
    assert reopened["plan"] == result


def test_plans_saved_before_transit_still_open(client: TestClient, seeded: Session) -> None:
    # A snapshot in the old format: none of the transit fields.
    old = plan(client, mode="WALK", days=1)
    for day in old["days"]:
        del day["return_leg"], day["transit_available"]
        for stop in day["stops"]:
            del stop["leg_from_previous"]
    token = client.post("/api/v1/auth/register", json={"email": "old@example.com", "password": PASSWORD})
    headers = {"Authorization": f"Bearer {token.json()['access_token']}"}
    user_id = client.get("/api/v1/auth/me", headers=headers).json()["id"]
    route = SavedRoute(
        name="Old route",
        user_id=user_id,
        city_id=CITY_ID,
        accommodation_lat=HOTEL["lat"],
        accommodation_lng=HOTEL["lng"],
        duration_days=1,
        travel_mode="WALK",
        plan=old,
    )
    seeded.add(route)
    seeded.commit()

    resp = client.get(f"/api/v1/routes/{route.id}", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["plan"]["days"][0]["return_leg"] is None


def test_transit_routing_is_limited_per_client(
    client: TestClient, fake: FakeTransitClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(TRANSIT_ROUTINGS_PER_IP, "limit", 2)
    body = {"city_id": CITY_ID, "accommodation": HOTEL, "duration_days": 1, "travel_mode": "TRANSIT"}
    assert [client.post("/api/v1/routes/plan", json=body).status_code for _ in range(3)] == [200, 200, 429]
    # Walking and driving plans don't count against it (routed by estimates here).
    app.dependency_overrides[get_routes_client] = lambda: None
    assert client.post("/api/v1/routes/plan", json={**body, "travel_mode": "WALK"}).status_code == 200


def test_an_unknown_time_zone_falls_back_to_utc() -> None:
    assert city_timezone(City(id="x", name="X", currency_code="EUR", timezone="Not/A_Zone")) is UTC
    assert str(city_timezone(City(id="y", name="Y", currency_code="TRY", timezone="Europe/Istanbul"))) == (
        "Europe/Istanbul"
    )

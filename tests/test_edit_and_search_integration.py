"""Removing stops, updating saved routes, account deletion, login lockout and place search."""

from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.v1.routes_places import get_place_search_client
from app.main import app
from app.services.geo import LatLng
from app.services.place_search import PlaceLocation, PlaceSearchError, Suggestion
from tests.seed import CITY_ID, HOTEL

PASSWORD = "s3cure-enough-password"


def register(client: TestClient, email: str = "ada@example.com") -> dict[str, str]:
    resp = client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 201, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def make_plan(client: TestClient, days: int = 2) -> dict[str, Any]:
    resp = client.post("/api/v1/routes/plan", json={"city_id": CITY_ID, "accommodation": HOTEL, "duration_days": days})
    assert resp.status_code == 200, resp.text
    return resp.json()


def stop_ids(day: dict[str, Any]) -> list[str]:
    return [s["poi_id"] for s in day["stops"]]


# --- removing stops ----------------------------------------------------------------------------


def test_remove_stop_reroutes_only_that_day(client: TestClient) -> None:
    plan = make_plan(client)
    day1, day2 = plan["days"]
    removed = day1["stops"][0]["poi_id"]

    resp = client.post("/api/v1/routes/plan/remove-stop", json={"plan": plan, "poi_id": removed})
    assert resp.status_code == 200, resp.text
    new = resp.json()

    new_day1, new_day2 = new["days"]
    assert removed not in stop_ids(new_day1)
    assert sorted(stop_ids(new_day1)) == sorted(stop_ids(day1)[1:])
    assert [s["order_in_day"] for s in new_day1["stops"]] == list(range(1, len(new_day1["stops"]) + 1))
    assert new_day2 == day2  # untouched

    # Totals follow the remaining stops.
    stops = [s for d in new["days"] for s in d["stops"]]
    priced = [Decimal(s["entry_price"]) for s in stops if s["entry_price"] is not None]
    assert Decimal(new["total_entry_cost"]) == sum(priced)
    assert new["unpriced_stop_count"] == len(stops) - len(priced)


def test_removing_the_last_stop_leaves_an_empty_day(client: TestClient) -> None:
    plan = make_plan(client, days=1)
    for stop in list(plan["days"][0]["stops"]):
        plan = client.post("/api/v1/routes/plan/remove-stop", json={"plan": plan, "poi_id": stop["poi_id"]}).json()
    assert plan["days"][0]["stops"] == []
    assert plan["total_entry_cost"] == "0"


def test_remove_stop_that_is_not_in_the_plan(client: TestClient) -> None:
    resp = client.post("/api/v1/routes/plan/remove-stop", json={"plan": make_plan(client), "poi_id": "nope"})
    assert resp.status_code == 404


def test_remove_stop_rejects_foreign_places(client: TestClient) -> None:
    plan = make_plan(client)
    plan["days"][0]["stops"][1]["poi_id"] = "not-a-real-poi"
    removed = plan["days"][0]["stops"][0]["poi_id"]
    resp = client.post("/api/v1/routes/plan/remove-stop", json={"plan": plan, "poi_id": removed})
    assert resp.status_code == 422


# --- updating saved routes ------------------------------------------------------------------------


def test_update_saved_route_after_removing_a_stop(client: TestClient) -> None:
    auth = register(client)
    plan = make_plan(client)
    saved = client.post("/api/v1/routes", json={"name": "Trip", "plan": plan}, headers=auth).json()

    removed = plan["days"][0]["stops"][0]["poi_id"]
    edited = client.post("/api/v1/routes/plan/remove-stop", json={"plan": plan, "poi_id": removed}).json()
    resp = client.put(f"/api/v1/routes/{saved['id']}", json={"plan": edited}, headers=auth)
    assert resp.status_code == 200, resp.text
    updated = resp.json()
    assert updated["name"] == "Trip"  # kept when not given
    assert updated["stop_count"] == saved["stop_count"] - 1
    assert updated["plan"] == edited

    listed = client.get("/api/v1/routes", headers=auth).json()
    assert [(r["id"], r["stop_count"]) for r in listed] == [(saved["id"], saved["stop_count"] - 1)]


def test_cannot_update_someone_elses_route(client: TestClient) -> None:
    ada = register(client, "ada@example.com")
    bob = register(client, "bob@example.com")
    plan = make_plan(client)
    route_id = client.post("/api/v1/routes", json={"plan": plan}, headers=ada).json()["id"]
    assert client.put(f"/api/v1/routes/{route_id}", json={"plan": plan}, headers=bob).status_code == 404


# --- account deletion ---------------------------------------------------------------------------


def test_delete_account_needs_the_password_and_removes_everything(client: TestClient) -> None:
    auth = register(client)
    client.post("/api/v1/routes", json={"plan": make_plan(client)}, headers=auth)

    wrong = client.request("DELETE", "/api/v1/auth/me", json={"password": "wrong-password"}, headers=auth)
    assert wrong.status_code == 403
    assert client.get("/api/v1/auth/me", headers=auth).status_code == 200

    ok = client.request("DELETE", "/api/v1/auth/me", json={"password": PASSWORD}, headers=auth)
    assert ok.status_code == 204
    assert client.get("/api/v1/auth/me", headers=auth).status_code == 401  # token no longer maps to a user
    login = client.post("/api/v1/auth/login", data={"username": "ada@example.com", "password": PASSWORD})
    assert login.status_code == 401


# --- brute-force protection -----------------------------------------------------------------------


def test_login_locks_an_account_after_repeated_wrong_passwords(client: TestClient) -> None:
    register(client)
    for _ in range(10):
        resp = client.post("/api/v1/auth/login", data={"username": "ada@example.com", "password": "guess-guess"})
        assert resp.status_code == 401
    locked = client.post("/api/v1/auth/login", data={"username": "ada@example.com", "password": PASSWORD})
    assert locked.status_code == 429  # even the right password waits now
    assert int(locked.headers["Retry-After"]) > 0


# --- place search ---------------------------------------------------------------------------------


class FakePlaceSearch:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, ...]] = []

    async def autocomplete(self, text: str, near: LatLng, session_token: str, language: str) -> list[Suggestion]:
        self.calls.append(("autocomplete", text, session_token, language))
        if self.fail:
            raise PlaceSearchError("boom")
        return [Suggestion("ChIJhotel0000001", "Hotel Test", "Test City")]

    async def location(self, place_id: str, session_token: str, language: str) -> PlaceLocation:
        self.calls.append(("location", place_id, session_token, language))
        return PlaceLocation(place_id, LatLng(HOTEL["lat"], HOTEL["lng"]), "1 Test Street")


@pytest.fixture
def fake_places(client: TestClient) -> FakePlaceSearch:
    fake = FakePlaceSearch()
    app.dependency_overrides[get_place_search_client] = lambda: fake
    return fake


def test_place_autocomplete_and_location(client: TestClient, fake_places: FakePlaceSearch) -> None:
    params = {"q": "hotel", "lat": HOTEL["lat"], "lng": HOTEL["lng"], "session_token": "sess-12345678", "lang": "tr"}
    resp = client.get("/api/v1/places/autocomplete", params=params)
    assert resp.status_code == 200
    assert resp.json() == [{"place_id": "ChIJhotel0000001", "main_text": "Hotel Test", "secondary_text": "Test City"}]

    loc = client.get("/api/v1/places/ChIJhotel0000001", params={"session_token": "sess-12345678", "lang": "tr"})
    assert loc.status_code == 200
    assert loc.json() == {
        "place_id": "ChIJhotel0000001",
        "lat": HOTEL["lat"],
        "lng": HOTEL["lng"],
        "address": "1 Test Street",
    }
    # One session token for the whole search: that's what makes Google bill it as one session.
    assert {call[2] for call in fake_places.calls} == {"sess-12345678"}


def test_place_search_validates_input(client: TestClient, fake_places: FakePlaceSearch) -> None:
    base = {"lat": 0, "lng": 0, "session_token": "sess-12345678"}
    assert client.get("/api/v1/places/autocomplete", params={**base, "q": "a"}).status_code == 422
    assert client.get("/api/v1/places/autocomplete", params={**base, "q": "ok", "lang": "de"}).status_code == 422
    assert client.get("/api/v1/places/bad$id!!", params={"session_token": "sess-12345678"}).status_code == 422
    assert fake_places.calls == []


def test_place_search_upstream_failure_is_a_502(client: TestClient) -> None:
    app.dependency_overrides[get_place_search_client] = lambda: FakePlaceSearch(fail=True)
    params = {"q": "hotel", "lat": 0, "lng": 0, "session_token": "sess-12345678"}
    assert client.get("/api/v1/places/autocomplete", params=params).status_code == 502


def test_place_search_without_api_key_is_a_503(client: TestClient) -> None:
    saved = app.state.place_search_client
    app.state.place_search_client = None
    try:
        params = {"q": "hotel", "lat": 0, "lng": 0, "session_token": "sess-12345678"}
        assert client.get("/api/v1/places/autocomplete", params=params).status_code == 503
    finally:
        app.state.place_search_client = saved


def test_place_search_is_rate_limited(client: TestClient, fake_places: FakePlaceSearch) -> None:
    params = {"q": "hotel", "lat": 0, "lng": 0, "session_token": "sess-12345678"}
    statuses = [client.get("/api/v1/places/autocomplete", params=params).status_code for _ in range(61)]
    assert statuses[:60] == [200] * 60
    assert statuses[60] == 429

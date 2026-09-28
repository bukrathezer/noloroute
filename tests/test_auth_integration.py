"""Accounts and saved routes against a real PostgreSQL database (rolled back after each test)."""

from typing import Any

from fastapi.testclient import TestClient

from tests.seed import CITY_ID, HOTEL

PASSWORD = "s3cure-enough-password"


def register(client: TestClient, email: str) -> dict[str, str]:
    resp = client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 201, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def make_plan(client: TestClient, days: int = 2) -> dict[str, Any]:
    resp = client.post("/api/v1/routes/plan", json={"city_id": CITY_ID, "accommodation": HOTEL, "duration_days": days})
    assert resp.status_code == 200, resp.text
    return resp.json()


# --- accounts --------------------------------------------------------------------------------


def test_register_returns_a_working_token(client: TestClient) -> None:
    resp = client.post("/api/v1/auth/register", json={"email": "  Ada@Example.com ", "password": PASSWORD})
    assert resp.status_code == 201
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["email"] == "ada@example.com"  # normalised

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == "ada@example.com"


def test_register_rejects_duplicate_email_in_any_case(client: TestClient) -> None:
    register(client, "ada@example.com")
    resp = client.post("/api/v1/auth/register", json={"email": "ADA@example.com", "password": PASSWORD})
    assert resp.status_code == 409


def test_register_validates_input(client: TestClient) -> None:
    assert client.post("/api/v1/auth/register", json={"email": "not-an-email", "password": PASSWORD}).status_code == 422
    assert client.post("/api/v1/auth/register", json={"email": "a@example.com", "password": "short"}).status_code == 422


def test_login(client: TestClient) -> None:
    register(client, "ada@example.com")
    ok = client.post("/api/v1/auth/login", data={"username": "Ada@example.com", "password": PASSWORD})
    assert ok.status_code == 200
    assert ok.json()["access_token"]

    wrong_password = client.post("/api/v1/auth/login", data={"username": "ada@example.com", "password": "nope-nope"})
    unknown_email = client.post("/api/v1/auth/login", data={"username": "who@example.com", "password": PASSWORD})
    assert wrong_password.status_code == unknown_email.status_code == 401
    # Same answer either way, so the endpoint can't be used to find out who has an account.
    assert wrong_password.json() == unknown_email.json()


def test_me_requires_a_valid_token(client: TestClient) -> None:
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-token"}).status_code == 401


# --- saved routes ------------------------------------------------------------------------------


def test_save_list_open_and_delete_a_route(client: TestClient) -> None:
    auth = register(client, "ada@example.com")
    plan = make_plan(client)
    stop_count = sum(len(d["stops"]) for d in plan["days"])

    saved = client.post("/api/v1/routes", json={"plan": plan}, headers=auth)
    assert saved.status_code == 201, saved.text
    route = saved.json()
    assert route["name"] == "Test City · 2 days"  # default name
    assert route["stop_count"] == stop_count
    assert route["plan"] == plan  # the snapshot comes back exactly as saved

    listed = client.get("/api/v1/routes", headers=auth).json()
    assert [(r["id"], r["stop_count"]) for r in listed] == [(route["id"], stop_count)]

    opened = client.get(f"/api/v1/routes/{route['id']}", headers=auth)
    assert opened.status_code == 200
    assert opened.json()["plan"] == plan

    assert client.delete(f"/api/v1/routes/{route['id']}", headers=auth).status_code == 204
    assert client.get(f"/api/v1/routes/{route['id']}", headers=auth).status_code == 404
    assert client.get("/api/v1/routes", headers=auth).json() == []


def test_save_uses_a_custom_name(client: TestClient) -> None:
    auth = register(client, "ada@example.com")
    resp = client.post("/api/v1/routes", json={"name": "  Honeymoon  ", "plan": make_plan(client)}, headers=auth)
    assert resp.json()["name"] == "Honeymoon"


def test_saved_routes_are_private(client: TestClient) -> None:
    ada = register(client, "ada@example.com")
    bob = register(client, "bob@example.com")
    route_id = client.post("/api/v1/routes", json={"plan": make_plan(client)}, headers=ada).json()["id"]

    assert client.get("/api/v1/routes", headers=bob).json() == []
    assert client.get(f"/api/v1/routes/{route_id}", headers=bob).status_code == 404
    assert client.delete(f"/api/v1/routes/{route_id}", headers=bob).status_code == 404
    assert client.get(f"/api/v1/routes/{route_id}", headers=ada).status_code == 200  # still there


def test_saved_route_endpoints_require_login(client: TestClient) -> None:
    assert client.post("/api/v1/routes", json={"plan": make_plan(client)}).status_code == 401
    assert client.get("/api/v1/routes").status_code == 401


def test_save_rejects_places_outside_the_city(client: TestClient) -> None:
    auth = register(client, "ada@example.com")
    plan = make_plan(client)
    plan["days"][0]["stops"][0]["poi_id"] = "not-a-real-poi"
    resp = client.post("/api/v1/routes", json={"plan": plan}, headers=auth)
    assert resp.status_code == 422
    assert "not-a-real-poi" in resp.text

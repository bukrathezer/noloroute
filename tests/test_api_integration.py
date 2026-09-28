"""Endpoint tests against a real PostgreSQL database (skipped when none is reachable).

Each test runs inside a transaction that is rolled back afterwards, so the test data never
persists and the local development database stays untouched.
"""

from collections.abc import Iterator
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.api.v1.routes_route import get_routes_client
from app.db.session import engine, get_db
from app.main import app
from app.models import POI, City

CITY_ID = "test-city"
HOTEL = {"lat": 48.8566, "lng": 2.3522}


@pytest.fixture
def db_session() -> Iterator[Session]:
    try:
        connection = engine.connect()
    except OperationalError:
        pytest.skip("PostgreSQL is not reachable")
    transaction = connection.begin()
    # Commits inside the app become savepoints, so the outer rollback still undoes everything.
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def seeded(db_session: Session) -> Session:
    db_session.add(City(id=CITY_ID, name="Test City", currency_code="EUR"))
    for i in range(12):
        db_session.add(
            POI(
                city_id=CITY_ID,
                place_id=f"test-place-{i}",
                name=f"Sight {i}",
                category=["MUSEUM", "PARK", "LANDMARK"][i % 3],
                latitude=HOTEL["lat"] + (i % 4 - 1.5) * 0.01,
                longitude=HOTEL["lng"] + (i // 4 - 1) * 0.015,
                avg_duration_min=60,
                entry_price=Decimal("10.00") if i % 2 == 0 else None,
                rating=4.5,
                user_rating_count=1000 + i * 100,
            )
        )
    db_session.flush()
    return db_session


@pytest.fixture
def client(seeded: Session) -> Iterator[TestClient]:
    app.dependency_overrides[get_db] = lambda: seeded
    app.dependency_overrides[get_routes_client] = lambda: None  # no Google calls: use estimates
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


def test_list_cities_includes_poi_count(client: TestClient) -> None:
    cities = {c["id"]: c for c in client.get("/api/v1/cities").json()}
    city = cities[CITY_ID]
    assert {k: city[k] for k in ("id", "name", "currency_code", "poi_count")} == {
        "id": CITY_ID,
        "name": "Test City",
        "currency_code": "EUR",
        "poi_count": 12,
    }
    # The centre is the average POI position, which the seed data places around the hotel.
    assert city["center_lat"] == pytest.approx(HOTEL["lat"], abs=0.02)
    assert city["center_lng"] == pytest.approx(HOTEL["lng"], abs=0.02)


def test_plan_route(client: TestClient) -> None:
    resp = client.post("/api/v1/routes/plan", json={"city_id": CITY_ID, "accommodation": HOTEL, "duration_days": 2})
    assert resp.status_code == 200
    plan = resp.json()
    assert plan["currency_code"] == "EUR"
    assert [d["day_number"] for d in plan["days"]] == [1, 2]
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

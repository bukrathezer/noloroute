"""The admin page: only for the addresses in ADMIN_EMAILS, and what it counts."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import EmailCode, PlanLog, SavedRoute, SharedPlan, User
from tests.accounts import PASSWORD, sign_up
from tests.seed import CITY_ID, HOTEL

ADMIN = "boss@example.com"


@pytest.fixture(autouse=True)
def nobody_yet(seeded: Session) -> None:
    """Start from no accounts, plans or shares (a local database may hold some; all rolled back)."""
    for model in (SharedPlan, SavedRoute, PlanLog, EmailCode, User):
        seeded.execute(delete(model))
    seeded.flush()


@pytest.fixture
def admin(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """The admin's auth header (with another address in the list too, and spaces)."""
    monkeypatch.setattr(get_settings(), "admin_emails", f" someone@example.com , {ADMIN.upper()} ")
    return sign_up(client, ADMIN)


def plan(client: TestClient, days: int = 2, mode: str = "WALK") -> dict:
    body = {"city_id": CITY_ID, "accommodation": HOTEL, "duration_days": days, "travel_mode": mode}
    resp = client.post("/api/v1/routes/plan", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_only_admins_see_the_page(client: TestClient, admin: dict[str, str]) -> None:
    other = sign_up(client, "ada@example.com")
    for path in ("/api/v1/admin/overview", "/api/v1/admin/users"):
        assert client.get(path).status_code == 401
        assert client.get(path, headers=other).status_code == 404  # as if there were no such page
        assert client.get(path, headers=admin).status_code == 200
    assert client.get("/api/v1/auth/me", headers=admin).json()["is_admin"] is True
    assert client.get("/api/v1/auth/me", headers=other).json()["is_admin"] is False


def test_an_unconfirmed_account_with_the_address_is_no_admin(
    client: TestClient, seeded: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "admin_emails", ADMIN)
    headers = sign_up(client, ADMIN)
    seeded.scalar(select(User).where(User.email == ADMIN)).email_verified_at = None
    seeded.flush()
    assert client.get("/api/v1/admin/overview", headers=headers).status_code == 404


def test_without_admin_emails_nobody_is_admin(client: TestClient) -> None:
    headers = sign_up(client, ADMIN)
    assert client.get("/api/v1/admin/overview", headers=headers).status_code == 404


def test_plans_are_counted_without_who_made_them(client: TestClient, seeded: Session) -> None:
    plan(client, days=2, mode="WALK")
    plan(client, days=3, mode="DRIVE")
    logged = seeded.scalars(select(PlanLog).order_by(PlanLog.duration_days)).all()
    assert [(p.city_id, p.travel_mode, p.duration_days) for p in logged] == [
        (CITY_ID, "WALK", 2),
        (CITY_ID, "DRIVE", 3),
    ]
    # Only the city, the travel mode and the length: no account, no hotel.
    assert set(PlanLog.__table__.columns.keys()) == {"id", "city_id", "travel_mode", "duration_days", "created_at"}


def test_a_failed_plan_is_not_counted(client: TestClient, seeded: Session) -> None:
    resp = client.post(
        "/api/v1/routes/plan",
        json={"city_id": CITY_ID, "accommodation": {"lat": 41.0, "lng": 28.9}, "duration_days": 1},
    )
    assert resp.status_code == 422
    assert seeded.scalars(select(PlanLog)).all() == []


def test_the_overview_counts(client: TestClient, admin: dict[str, str], seeded: Session) -> None:
    ada = sign_up(client, "ada@example.com")
    sign_up(client, "old@example.com")
    old = seeded.scalar(select(User).where(User.email == "old@example.com"))
    old.created_at = datetime.now(UTC) - timedelta(days=40)
    seeded.flush()

    first = plan(client)
    plan(client)
    assert client.post("/api/v1/routes", json={"plan": first}, headers=ada).status_code == 201
    assert client.post("/api/v1/shares", json={"plan": first}).status_code == 201

    data = client.get("/api/v1/admin/overview", headers=admin).json()
    assert data["users"] == {
        "total": 3,
        "verified": 3,
        "with_google": 0,
        "with_password": 3,
        "new_last_7_days": 2,
        "new_last_30_days": 2,
    }
    assert (data["plans_total"], data["plans_last_7_days"], data["plans_last_30_days"]) == (2, 2, 2)
    assert (data["saved_routes"], data["users_with_saved_routes"]) == (1, 1)
    assert (data["shared_plans"], data["shared_plans_last_7_days"]) == (1, 1)
    assert data["top_cities"] == [
        {
            "city_id": CITY_ID,
            "name": "Test City",
            "name_tr": "Test Şehri",
            "plans_last_30_days": 2,
            "saved_routes": 1,
            "shared_plans": 1,
        }
    ]
    # Every day of the last 30 listed, oldest first, ending today.
    for series in (data["signups_by_day"], data["plans_by_day"]):
        assert len(series) == 30
        assert series[-1]["day"] == datetime.now(UTC).date().isoformat()
        assert [d["day"] for d in series] == sorted(d["day"] for d in series)
    assert data["plans_by_day"][-1]["count"] == 2
    assert sum(d["count"] for d in data["signups_by_day"]) == 2


def test_the_user_list(client: TestClient, admin: dict[str, str]) -> None:
    ada = sign_up(client, "ada@example.com")
    sign_up(client, "grace@example.com")
    assert client.post("/api/v1/routes", json={"plan": plan(client)}, headers=ada).status_code == 201

    page = client.get("/api/v1/admin/users", headers=admin).json()
    assert page["total"] == 3
    rows = {u["email"]: u for u in page["users"]}
    assert rows["ada@example.com"]["saved_routes"] == 1
    assert rows["grace@example.com"]["saved_routes"] == 0
    assert rows["ada@example.com"]["verified"] and rows["ada@example.com"]["has_password"]
    assert not rows["ada@example.com"]["google"]
    assert rows["ada@example.com"]["last_login_at"] is not None  # confirming the address logged in
    assert all("password" not in key or key == "has_password" for key in rows["ada@example.com"])

    found = client.get("/api/v1/admin/users", params={"q": " ADA@ "}, headers=admin).json()
    assert (found["total"], [u["email"] for u in found["users"]]) == (1, ["ada@example.com"])
    # The search is plain text, not a pattern.
    assert client.get("/api/v1/admin/users", params={"q": "%"}, headers=admin).json()["total"] == 0

    first = client.get("/api/v1/admin/users", params={"limit": 2}, headers=admin).json()["users"]
    rest = client.get("/api/v1/admin/users", params={"limit": 2, "offset": 2}, headers=admin).json()["users"]
    assert len(first) == 2 and len(rest) == 1
    assert client.get("/api/v1/admin/users", params={"limit": 500}, headers=admin).status_code == 422


def test_logging_in_notes_the_time(client: TestClient, seeded: Session) -> None:
    sign_up(client, "ada@example.com")
    user = seeded.scalar(select(User).where(User.email == "ada@example.com"))
    user.last_login_at = None
    seeded.flush()
    resp = client.post("/api/v1/auth/login", data={"username": "ada@example.com", "password": PASSWORD})
    assert resp.status_code == 200
    seeded.refresh(user)
    assert user.last_login_at is not None


def test_a_plan_is_given_even_if_counting_it_fails(
    client: TestClient, seeded: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken_commit() -> None:
        raise RuntimeError("database gone")

    monkeypatch.setattr(seeded, "commit", broken_commit)
    resp = client.post("/api/v1/routes/plan", json={"city_id": CITY_ID, "accommodation": HOTEL, "duration_days": 1})
    assert resp.status_code == 200
    assert resp.json()["currency_code"] == "EUR"


def test_days_are_utc_days_whatever_the_database_zone(
    client: TestClient, admin: dict[str, str], seeded: Session
) -> None:
    seeded.execute(text("SET TIME ZONE 'Pacific/Kiritimati'"))  # UTC+14: late UTC is "tomorrow" there
    today = datetime.now(UTC).date()
    late_yesterday = datetime.combine(today - timedelta(days=1), datetime.min.time(), UTC) + timedelta(hours=23)
    seeded.add(PlanLog(city_id=CITY_ID, travel_mode="WALK", duration_days=1, created_at=late_yesterday))
    # Just before the 30 days began: not counted anywhere.
    first_day = datetime.combine(today - timedelta(days=29), datetime.min.time(), UTC)
    seeded.add(
        PlanLog(city_id=CITY_ID, travel_mode="WALK", duration_days=1, created_at=first_day - timedelta(minutes=1))
    )
    seeded.flush()

    data = client.get("/api/v1/admin/overview", headers=admin).json()
    by_day = {d["day"]: d["count"] for d in data["plans_by_day"]}
    assert by_day[(today - timedelta(days=1)).isoformat()] == 1
    assert sum(by_day.values()) == data["plans_last_30_days"] == 1
    assert data["plans_total"] == 2


def test_the_admin_page_is_left_out_of_the_api_docs(client: TestClient) -> None:
    assert not [p for p in client.get("/openapi.json").json()["paths"] if p.startswith("/api/v1/admin")]

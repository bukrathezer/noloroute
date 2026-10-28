"""Plans shared by link, against a real PostgreSQL database (rolled back after each test)."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1 import routes_share
from app.main import app
from app.models import POI, SharedPlan
from tests.seed import CITY_ID
from tests.test_auth_integration import make_plan

INDEX_HTML = """<!doctype html>
<html lang="en">
  <head>
    <meta name="description" content="Day-by-day travel routes." />
    <meta property="og:title" content="NoloRoute" />
    <meta property="og:description" content="Day-by-day travel routes." />
    <meta property="og:url" content="https://noloroute.com/" />
    <title>NoloRoute</title>
  </head>
  <body><div id="root"></div></body>
</html>
"""


@contextmanager
def frontend_index(path: Path) -> Iterator[None]:
    """Point the app at another index.html for a while. Not with monkeypatch: since pytest 9.2 its
    undo deletes attributes of Starlette's State, which live outside the instance's __dict__."""
    saved = app.state.frontend_index
    app.state.frontend_index = path
    try:
        yield
    finally:
        app.state.frontend_index = saved


@pytest.fixture
def built_frontend(tmp_path: Path) -> Iterator[Path]:
    index = tmp_path / "index.html"
    index.write_text(INDEX_HTML, encoding="utf-8")
    with frontend_index(index):
        yield index


def share(client: TestClient, plan: dict[str, Any], lang: str = "en") -> str:
    resp = client.post("/api/v1/shares", json={"plan": plan, "lang": lang})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["path"] == f"/p/{body['id']}"
    return body["id"]


def test_a_shared_plan_opens_for_anyone(client: TestClient) -> None:
    plan = make_plan(client)
    share_id = share(client, plan)
    assert routes_share.SHARE_ID.fullmatch(share_id)

    resp = client.get(f"/api/v1/shares/{share_id}")  # no login
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == share_id and body["created_at"]
    assert body["plan"]["days"] == plan["days"]


def test_sharing_the_same_plan_again_keeps_the_link(client: TestClient) -> None:
    plan = make_plan(client)
    first = share(client, plan)
    assert share(client, plan) == first
    assert share(client, plan, lang="tr") != first  # its preview is in another language
    other = make_plan(client, days=1)
    assert share(client, other) != first


def test_unknown_and_malformed_links_are_not_found(client: TestClient) -> None:
    assert client.get("/api/v1/shares/AAAAAAAA").status_code == 404
    assert client.get("/api/v1/shares/not-an-id!").status_code == 404


def test_sharing_rejects_places_outside_the_city(client: TestClient) -> None:
    plan = make_plan(client)
    plan["days"][0]["stops"][0]["poi_id"] = "not-a-place-here"
    assert client.post("/api/v1/shares", json={"plan": plan}).status_code == 422


def test_sharing_rejects_oversized_plans(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(routes_share, "MAX_SHARED_PLAN_BYTES", 100)
    assert client.post("/api/v1/shares", json={"plan": make_plan(client)}).status_code == 413


def test_sharing_is_rate_limited(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(routes_share.SHARES_PER_IP, "limit", 2)
    plan = make_plan(client)
    assert client.post("/api/v1/shares", json={"plan": plan}).status_code == 201
    assert client.post("/api/v1/shares", json={"plan": plan}).status_code == 201
    resp = client.post("/api/v1/shares", json={"plan": plan})
    assert resp.status_code == 429 and resp.headers["Retry-After"]


def test_a_shared_plan_shows_the_places_current_names(client: TestClient, seeded: Session) -> None:
    plan = make_plan(client)
    share_id = share(client, plan)
    first = plan["days"][0]["stops"][0]
    seeded.scalar(select(POI).where(POI.id == first["poi_id"])).name_tr = "Yeni Türkçe Ad"
    seeded.flush()
    stop = client.get(f"/api/v1/shares/{share_id}").json()["plan"]["days"][0]["stops"][0]
    assert stop["name_tr"] == "Yeni Türkçe Ad"


def test_the_link_page_previews_the_plan(client: TestClient, built_frontend: Path) -> None:
    plan = make_plan(client)
    stops = [stop for day in plan["days"] for stop in day["stops"]]
    share_id = share(client, plan, lang="en")

    resp = client.get(f"/p/{share_id}?fbclid=tracking")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert resp.headers["cache-control"] == "no-cache"
    assert resp.headers["x-robots-tag"] == "noindex"
    page = resp.text
    assert "<title>Test City · 2-day trip plan · NoloRoute</title>" in page
    assert '<meta property="og:title" content="Test City · 2-day trip plan" />' in page
    named = ", ".join(stop["name"] for stop in stops[:4])
    description = f"{len(stops)} stops: {named} and {len(stops) - 4} more."
    assert f'<meta property="og:description" content="{description}" />' in page
    assert f'<meta name="description" content="{description}" />' in page
    assert f'<meta property="og:url" content="http://testserver/p/{share_id}" />' in page  # no query
    assert '<div id="root"></div>' in page  # the app itself is unchanged


def test_the_link_page_answers_head_requests(client: TestClient, built_frontend: Path) -> None:
    share_id = share(client, make_plan(client))
    resp = client.head(f"/p/{share_id}")
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/html")


def test_the_link_page_previews_in_the_sharers_language(client: TestClient, built_frontend: Path) -> None:
    share_id = share(client, make_plan(client, days=1), lang="tr")
    page = client.get(f"/p/{share_id}").text
    assert '<html lang="tr">' in page
    assert "<title>Test Şehri · 1 günlük gezi planı · NoloRoute</title>" in page
    assert " durak: " in page


def test_an_unknown_link_page_still_loads_the_app(client: TestClient, built_frontend: Path) -> None:
    resp = client.get("/p/AAAAAAAA")
    assert resp.status_code == 404
    assert resp.text == INDEX_HTML  # the app says the link was not found


def test_link_preview_escapes_names() -> None:
    page = routes_share.with_preview(INDEX_HTML, "en", 'A "quoted" <b>', "x & y", url="https://noloroute.com/p/x")
    assert "<title>A &quot;quoted&quot; &lt;b&gt; · NoloRoute</title>" in page
    assert '<meta property="og:description" content="x &amp; y" />' in page


def test_the_link_page_needs_a_built_frontend(client: TestClient, tmp_path: Path) -> None:
    share_id = share(client, make_plan(client))
    with frontend_index(tmp_path / "missing.html"):
        assert client.get(f"/p/{share_id}").status_code == 404


def test_a_shared_plan_says_only_what_the_database_says(client: TestClient, built_frontend: Path) -> None:
    plan = make_plan(client)
    real = plan["days"][0]["stops"][0]
    fake = {
        **real,
        "name": "Free tour! Call +00 000",
        "name_tr": "Bedava tur!",
        "category": "SCAM",
        "latitude": 0.0,
        "entry_price": "0.01",
        "rating": 5.0,
        "visit_minutes": 999,
        "hours": "call us",
        "leg_from_previous": {
            "mode": "TRANSIT",
            "rides": [
                {
                    "vehicle": "BUS",
                    "line": "X" * 500,
                    "line_color": "url(https://example.com/pixel)",
                    "line_text_color": "#ffffff",
                    "headsign": None,
                    "from_stop": "A",
                    "to_stop": "B",
                    "stop_count": 2,
                    "minutes": 5,
                    "agency": None,
                }
            ],
            "walk_minutes": 3,
            "alternative_mode": None,
            "alternative_minutes": None,
        },
    }
    plan["days"][0]["stops"][0] = fake
    plan["days"][0]["dropped_stops"] = ["Sight 11", "Visit our shop"]
    plan["days"][0]["dropped_stops_tr"] = ["Sight 11", "Dükkanımıza gelin"]
    plan["currency_code"] = "XXX"
    plan["total_entry_cost"] = "0"
    share_id = share(client, plan)

    shared = client.get(f"/api/v1/shares/{share_id}").json()["plan"]
    stop = shared["days"][0]["stops"][0]
    assert (stop["name"], stop["category"], stop["latitude"]) == (real["name"], real["category"], real["latitude"])
    assert (stop["entry_price"], stop["rating"], stop["visit_minutes"]) == (
        real["entry_price"],
        real["rating"],
        real["visit_minutes"],
    )
    assert stop["name_tr"] is None and stop["hours"] is None  # the seeded place has neither
    ride = stop["leg_from_previous"]["rides"][0]
    assert len(ride["line"]) == routes_share.MAX_RIDE_TEXT
    assert ride["line_color"] is None and ride["line_text_color"] == "#ffffff"
    assert shared["days"][0]["dropped_stops"] == ["Sight 11"]
    assert shared["days"][0]["dropped_stops_tr"] == ["Sight 11"]
    assert shared["currency_code"] == "EUR"
    assert shared["total_entry_cost"] == plan_cost(shared)
    assert "Free tour" not in client.get(f"/p/{share_id}").text


def plan_cost(plan: dict[str, Any]) -> str:
    prices = [Decimal(s["entry_price"]) for d in plan["days"] for s in d["stops"] if s["entry_price"] is not None]
    return str(sum(prices, Decimal(0)))


def test_sharing_stops_for_the_day_after_the_daily_limit(
    client: TestClient, seeded: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    # One more than the database already holds (a development database may have some from today).
    since = datetime.now(UTC) - timedelta(days=1)
    already = seeded.scalar(select(func.count()).where(SharedPlan.created_at > since)) or 0
    monkeypatch.setattr(routes_share, "MAX_SHARES_PER_DAY", already + 1)
    plan = make_plan(client)
    first = share(client, plan)
    assert share(client, plan) == first  # the same plan again creates nothing
    resp = client.post("/api/v1/shares", json={"plan": make_plan(client, days=1)})
    assert resp.status_code == 429


def test_the_shares_city_is_stored(client: TestClient, seeded: Session) -> None:
    share_id = share(client, make_plan(client))
    stored = seeded.get(SharedPlan, share_id)
    assert stored is not None and stored.city_id == CITY_ID and stored.lang == "en"

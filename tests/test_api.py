from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import FrontendFiles, app


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    # The context manager runs the app's lifespan (startup/shutdown), like a real server.
    with TestClient(app) as test_client:
        yield test_client


def test_health(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_plan_rejects_invalid_request(client: TestClient) -> None:
    # Request validation happens before any DB access.
    resp = client.post(
        "/api/v1/routes/plan",
        json={"city_id": "paris", "accommodation": {"lat": 48.85, "lng": 2.35}, "duration_days": 9},
    )
    assert resp.status_code == 422


def test_frontend_page_is_revalidated_and_hashed_assets_are_cached(tmp_path: Path) -> None:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><title>NoloRoute</title>")
    (tmp_path / "assets" / "index-3f2a9c.js").write_text("console.log('hi')")
    site = FastAPI()
    site.mount("/", FrontendFiles(directory=tmp_path, html=True))

    with TestClient(site) as client:
        page = client.get("/")
        assert page.headers["cache-control"] == "no-cache"
        # An unchanged page costs the browser only a 304.
        again = client.get("/", headers={"if-none-match": page.headers["etag"]})
        assert again.status_code == 304

        asset = client.get("/assets/index-3f2a9c.js")
        assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"

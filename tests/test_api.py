from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import app


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

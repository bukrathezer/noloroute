import os
from collections.abc import Iterator

import pytest

# Must be set before the app (and its cached settings) is imported. A value in .env or the
# environment wins, so local runs and CI both work.
os.environ.setdefault("JWT_SECRET_KEY", "test-only-jwt-secret-key-not-used-anywhere-else")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.api.v1.routes_route import get_routes_client  # noqa: E402
from app.core.rate_limit import reset_all_limiters  # noqa: E402
from app.db.session import engine, get_db  # noqa: E402
from app.main import app  # noqa: E402
from tests.seed import seed_city  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_rate_limits() -> None:
    # All test requests share one fake client IP; start every test with clean counters.
    reset_all_limiters()


@pytest.fixture
def db_session() -> Iterator[Session]:
    """A session inside a transaction that is rolled back afterwards (skipped without PostgreSQL)."""
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
    seed_city(db_session)
    return db_session


@pytest.fixture
def client(seeded: Session) -> Iterator[TestClient]:
    """API client wired to the rolled-back session, with Google routing replaced by estimates."""
    app.dependency_overrides[get_db] = lambda: seeded
    app.dependency_overrides[get_routes_client] = lambda: None
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()

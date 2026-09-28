from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

# pool_pre_ping checks a pooled connection before handing it out, so a DB restart
# doesn't surface as a stale-connection error on the next request.
# The pool is capped because Cloud Run may run several instances and the smallest Cloud SQL
# tier allows only ~25 connections in total.
engine = create_engine(get_settings().database_url, pool_pre_ping=True, pool_size=5, max_overflow=0)
SessionLocal = sessionmaker(bind=engine, autoflush=False)


def get_db() -> Generator[Session]:
    """FastAPI dependency: one session per request, always closed afterwards."""
    with SessionLocal() as db:
        yield db

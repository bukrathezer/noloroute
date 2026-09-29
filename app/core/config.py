from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env from the repo root so scripts and tests work regardless of the CWD.
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    database_url: str
    google_places_api_key: str | None = None
    # Ticketmaster Discovery API (events); without it the events lookup is off.
    ticketmaster_api_key: str | None = None

    # Signs login tokens. Optional here so one-off jobs (migrations, ingestion) don't need it;
    # the API refuses to start without it (see app.main).
    jwt_secret_key: str | None = None
    access_token_ttl_minutes: int = 60 * 24 * 7  # one week


@lru_cache
def get_settings() -> Settings:
    # Cached so .env is parsed once per process, not on every call.
    return Settings()

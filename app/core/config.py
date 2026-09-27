from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env from the repo root so scripts and tests work regardless of the CWD.
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    database_url: str
    google_places_api_key: str | None = None


@lru_cache
def get_settings() -> Settings:
    # Cached so .env is parsed once per process, not on every call.
    return Settings()

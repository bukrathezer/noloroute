from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env from the repo root so scripts and tests work regardless of the CWD.
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    database_url: str
    google_places_api_key: str | None = None
    # Resend (resend.com) sends the sign-up and password-reset codes; without a key they are only
    # logged (local development).
    resend_api_key: str | None = None
    email_from: str = "NoloRoute <hesap@noloroute.com>"
    # Ticketmaster Discovery API (events); without it the events lookup is off.
    ticketmaster_api_key: str | None = None

    # Signs login tokens. Optional here so one-off jobs (migrations, ingestion) don't need it;
    # the API refuses to start without it (see app.main).
    jwt_secret_key: str | None = None
    # How long a login lasts: with "remember me" (the browser keeps it), and without (only until
    # the browser closes, and at most this long).
    access_token_ttl_minutes: int = 60 * 24 * 30
    session_token_ttl_minutes: int = 60 * 12
    # Sign-in with Google: the OAuth client id from Google Cloud (public, it is in the page too).
    # Without it the Google button doesn't show.
    google_oauth_client_id: str | None = None
    # Who sees the admin page: email addresses, comma-separated (confirmed accounts only).
    admin_emails: str = ""


@lru_cache
def get_settings() -> Settings:
    # Cached so .env is parsed once per process, not on every call.
    return Settings()

"""Signing in with Google: checking ID tokens, and linking or creating accounts (the latter against
a real PostgreSQL database, rolled back after each test)."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.routes_auth import get_google_verifier
from app.core.security import hash_password
from app.main import app
from app.models import EmailCode, User
from app.services.google_auth import (
    GoogleIdentity,
    GoogleTokenError,
    GoogleUnavailableError,
    identity_from_token,
    is_authoritative,
)
from tests.accounts import PASSWORD, sign_up

CLIENT_ID = "test-client.apps.googleusercontent.com"
GOOGLE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def google_token(key=GOOGLE_KEY, **overrides) -> str:
    now = datetime.now(UTC)
    claims = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": "1234567890",
        "email": "Ada@Gmail.com",
        "email_verified": True,
        "iat": now,
        "exp": now + timedelta(hours=1),
    }
    claims.update(overrides)
    return jwt.encode({k: v for k, v in claims.items() if v is not None}, key, algorithm="RS256")


# --- checking tokens ---------------------------------------------------------------------------


def check(token: str) -> GoogleIdentity:
    return identity_from_token(token, GOOGLE_KEY.public_key(), CLIENT_ID)


def test_a_genuine_token_gives_the_account_id_and_email() -> None:
    assert check(google_token()) == GoogleIdentity(sub="1234567890", email="ada@gmail.com", authoritative=True)
    assert check(google_token(iss="accounts.google.com")).sub == "1234567890"  # Google uses both forms


def test_google_speaks_for_gmail_and_workspace_addresses_only() -> None:
    assert check(google_token(email="ada@example.com", hd="example.com")).authoritative  # Workspace
    assert not check(google_token(email="ada@example.com")).authoritative  # any other address
    assert not check(google_token(email="ada@example.com", hd="other.com")).authoritative


def test_a_little_clock_difference_is_allowed() -> None:
    assert check(google_token(exp=datetime.now(UTC) - timedelta(seconds=20))).sub == "1234567890"


@pytest.mark.parametrize(
    "token",
    [
        google_token(key=OTHER_KEY),  # not signed by Google
        google_token(aud="someone-elses-app.apps.googleusercontent.com"),
        google_token(iss="https://evil.example.com"),
        google_token(exp=datetime.now(UTC) - timedelta(minutes=5)),
        google_token(email_verified=False),
        google_token(email_verified=None),
        google_token(email=None),
        google_token(sub=None),
        "not-a-token",
    ],
)
def test_other_tokens_are_refused(token: str) -> None:
    with pytest.raises(GoogleTokenError):
        check(token)


# --- signing in -----------------------------------------------------------------------------------


class FakeVerifier:
    """Stands in for Google: credentials are "sub|email" strings, or the failure to raise."""

    client_id = CLIENT_ID

    def verify(self, credential: str) -> GoogleIdentity:
        if credential == "invalid":
            raise GoogleTokenError("bad token")
        if credential == "google-down":
            raise GoogleUnavailableError("no keys")
        if "|" not in credential:
            raise GoogleTokenError("not a token")
        sub, email = credential.split("|")
        return GoogleIdentity(sub=sub, email=email, authoritative=is_authoritative(email, None))


@pytest.fixture
def google(client: TestClient):
    app.dependency_overrides[get_google_verifier] = lambda: FakeVerifier()
    yield
    app.dependency_overrides.pop(get_google_verifier, None)


def google_login(client: TestClient, credential: str, remember: bool = True):
    return client.post("/api/v1/auth/google", json={"credential": credential, "remember": remember})


def login(client: TestClient, email: str, password: str = PASSWORD, remember: bool | None = None):
    form = {"username": email, "password": password}
    if remember is not None:
        form["remember"] = "true" if remember else "false"
    return client.post("/api/v1/auth/login", data=form)


def token_lifetime(token: str) -> timedelta:
    claims = jwt.decode(token, options={"verify_signature": False})
    return timedelta(seconds=claims["exp"] - claims["iat"])


def test_a_first_google_sign_in_creates_a_confirmed_account(client: TestClient, google, seeded: Session) -> None:
    resp = google_login(client, "g-1|ada@gmail.com")
    assert resp.status_code == 200
    body = resp.json()
    assert body["user"]["email"] == "ada@gmail.com" and body["user"]["has_password"] is False
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200 and me.json()["has_password"] is False
    user = seeded.scalar(select(User).where(User.email == "ada@gmail.com"))
    assert user.google_sub == "g-1" and user.email_verified_at is not None and user.hashed_password is None
    # No password to log in with (nor to guess).
    assert login(client, "ada@gmail.com", "any-password-at-all").status_code == 401


def test_signing_in_again_finds_the_account_by_its_google_id(client: TestClient, google) -> None:
    first = google_login(client, "g-1|ada@gmail.com").json()["user"]["id"]
    # The Google account's email changed since: still the same account.
    assert google_login(client, "g-1|ada.new@gmail.com").json()["user"]["id"] == first


def test_google_links_to_the_account_with_its_email(client: TestClient, google) -> None:
    sign_up(client, "ada@gmail.com")
    resp = google_login(client, "g-1|ada@gmail.com")
    assert resp.status_code == 200 and resp.json()["user"]["has_password"] is True
    assert login(client, "ada@gmail.com").status_code == 200  # the password still works


def test_google_takes_an_unconfirmed_account_from_whoever_started_it(
    client: TestClient, google, seeded: Session
) -> None:
    # Someone signed up with Ada's address and a password of their own, but never got the code.
    mallory = "mallorys-password"
    client.post("/api/v1/auth/register", json={"email": "ada@gmail.com", "password": mallory})
    code = client.outbox.last_code("ada@gmail.com")
    assert google_login(client, "g-1|ada@gmail.com").status_code == 200
    # Their password and code are gone; the account is Ada's (through Google).
    assert login(client, "ada@gmail.com", mallory).status_code == 401
    body = {"email": "ada@gmail.com", "code": code, "password": mallory}
    assert client.post("/api/v1/auth/verify-email", json=body).status_code == 400
    assert seeded.scalar(select(EmailCode).where(EmailCode.email == "ada@gmail.com")) is None


def test_an_account_elsewhere_is_linked_only_once_its_owner_logs_in(client: TestClient, google) -> None:
    # Google once confirmed this non-Gmail address for someone's Google account; that doesn't make
    # them the owner of the NoloRoute account of the address today.
    sign_up(client, "ada@example.com")
    resp = google_login(client, "g-1|ada@example.com")
    assert resp.status_code == 409 and resp.json()["detail"] == "link_with_password"
    assert login(client, "ada@example.com").status_code == 200


def test_an_unconfirmed_account_elsewhere_goes_to_google(client: TestClient, google) -> None:
    client.post("/api/v1/auth/register", json={"email": "ada@example.com", "password": "someone-elses"})
    assert google_login(client, "g-1|ada@example.com").status_code == 200
    assert login(client, "ada@example.com", "someone-elses").status_code == 401


def test_throwaway_addresses_cannot_sign_up_with_google_either(client: TestClient, google) -> None:
    resp = google_login(client, "g-1|ada@mailinator.com")
    assert resp.status_code == 422 and resp.json()["detail"] == "disposable_email"


def test_a_password_reset_ends_other_logins_and_unlinks_google(client: TestClient, google, seeded: Session) -> None:
    old = google_login(client, "g-1|ada@gmail.com").json()["access_token"]
    client.post("/api/v1/auth/forgot-password", json={"email": "ada@gmail.com"})
    code = client.outbox.last_code("ada@gmail.com")
    body = {"email": "ada@gmail.com", "code": code, "password": "taken-back-password"}
    new = client.post("/api/v1/auth/reset-password", json=body).json()["access_token"]
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {old}"}).status_code == 401
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {new}"}).status_code == 200
    assert seeded.scalar(select(User.google_sub).where(User.email == "ada@gmail.com")) is None
    # Google (which runs Gmail) can link it again.
    assert google_login(client, "g-1|ada@gmail.com").status_code == 200


def test_an_account_linked_to_another_google_account_is_refused(client: TestClient, google) -> None:
    google_login(client, "g-1|ada@gmail.com")
    resp = google_login(client, "g-2|ada@gmail.com")
    assert resp.status_code == 409 and resp.json()["detail"] == "google_account_mismatch"


def test_bad_tokens_and_google_outages(client: TestClient, google) -> None:
    assert google_login(client, "invalid").status_code == 401
    assert google_login(client, "google-down").status_code == 503


def test_without_a_client_id_there_is_no_google_sign_in(client: TestClient) -> None:
    app.dependency_overrides[get_google_verifier] = lambda: None
    try:
        assert google_login(client, "g-1|ada@gmail.com").status_code == 503
        assert client.get("/api/v1/auth/config").json() == {"google_client_id": None}
    finally:
        app.dependency_overrides.pop(get_google_verifier, None)


def test_the_config_gives_the_client_id(client: TestClient, google) -> None:
    assert client.get("/api/v1/auth/config").json() == {"google_client_id": CLIENT_ID}


def test_a_google_only_account_is_deleted_by_signing_in_with_google_again(client: TestClient, google) -> None:
    token = google_login(client, "g-1|ada@gmail.com").json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    def delete(body: dict) -> int:
        return client.request("DELETE", "/api/v1/auth/me", json=body, headers=headers).status_code

    assert delete({}) == 403  # a stolen token alone isn't enough
    assert delete({"google_credential": "g-2|bob@gmail.com"}) == 403  # another Google account
    assert delete({"google_credential": "g-1|ada@gmail.com"}) == 204
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401


def test_an_account_with_a_password_still_needs_it_to_be_deleted(client: TestClient) -> None:
    headers = sign_up(client, "ada@example.com")
    resp = client.request("DELETE", "/api/v1/auth/me", json={"email": "ada@example.com"}, headers=headers)
    assert resp.status_code == 403


def test_a_google_only_account_can_add_a_password_by_resetting_it(client: TestClient, google) -> None:
    google_login(client, "g-1|ada@gmail.com")
    client.post("/api/v1/auth/forgot-password", json={"email": "ada@gmail.com"})
    code = client.outbox.last_code("ada@gmail.com")
    body = {"email": "ada@gmail.com", "code": code, "password": "now-with-a-password"}
    resp = client.post("/api/v1/auth/reset-password", json=body)
    assert resp.status_code == 200 and resp.json()["user"]["has_password"] is True
    assert login(client, "ada@gmail.com", "now-with-a-password").status_code == 200


# --- remember me ----------------------------------------------------------------------------------


def test_remember_me_decides_how_long_a_login_lasts(client: TestClient, google, seeded: Session) -> None:
    sign_up(client, "ada@example.com")
    remembered = login(client, "ada@example.com").json()["access_token"]  # the default
    session = login(client, "ada@example.com", remember=False).json()["access_token"]
    assert token_lifetime(remembered) == timedelta(days=30)
    assert token_lifetime(session) == timedelta(hours=12)
    assert token_lifetime(google_login(client, "g-1|bob@gmail.com", remember=False).json()["access_token"]) == (
        timedelta(hours=12)
    )


def test_old_accounts_keep_working_with_a_password(client: TestClient, seeded: Session) -> None:
    seeded.add(
        User(email="old@example.com", hashed_password=hash_password(PASSWORD), email_verified_at=datetime.now(UTC))
    )
    seeded.flush()
    resp = login(client, "old@example.com")
    assert resp.status_code == 200 and resp.json()["user"]["has_password"] is True

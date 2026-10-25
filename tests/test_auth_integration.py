"""Accounts and saved routes against a real PostgreSQL database (rolled back after each test)."""

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.rate_limit import reset_all_limiters
from app.core.security import hash_password
from app.models import EmailCode, User
from tests.accounts import PASSWORD, sign_up
from tests.seed import CITY_ID, HOTEL


def register(client: TestClient, email: str) -> dict[str, str]:
    return sign_up(client, email)


def make_plan(client: TestClient, days: int = 2) -> dict[str, Any]:
    resp = client.post("/api/v1/routes/plan", json={"city_id": CITY_ID, "accommodation": HOTEL, "duration_days": days})
    assert resp.status_code == 200, resp.text
    return resp.json()


def login(client: TestClient, email: str, password: str = PASSWORD):
    return client.post("/api/v1/auth/login", data={"username": email, "password": password})


# --- accounts --------------------------------------------------------------------------------


def test_signing_up_emails_a_code_that_logs_the_account_in(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/auth/register", json={"email": "  Ada@Example.com ", "password": PASSWORD, "lang": "tr"}
    )
    assert resp.status_code == 202
    assert resp.json() == {"status": "code_sent", "email": "ada@example.com"}  # normalised
    [(to, subject, text)] = client.outbox.sent
    assert to == "ada@example.com" and "doğrulama kodun" in subject  # in the page's language
    code = client.outbox.last_code("ada@example.com")
    assert code in subject and code in text

    assert login(client, "ada@example.com").status_code == 403  # not before the code

    resp = client.post(
        "/api/v1/auth/verify-email", json={"email": "ada@example.com", "code": code, "password": PASSWORD}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer" and body["user"]["email"] == "ada@example.com"
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200 and me.json()["email"] == "ada@example.com"
    assert login(client, "ada@example.com").status_code == 200

    # A code works once.
    again = client.post(
        "/api/v1/auth/verify-email", json={"email": "ada@example.com", "code": code, "password": PASSWORD}
    )
    assert again.status_code == 400


def test_wrong_codes_run_out(client: TestClient) -> None:
    client.post("/api/v1/auth/register", json={"email": "ada@example.com", "password": PASSWORD})
    code = client.outbox.last_code("ada@example.com")
    wrong = f"{(int(code) + 1) % 1_000_000:06d}"
    for _ in range(5):
        resp = client.post(
            "/api/v1/auth/verify-email", json={"email": "ada@example.com", "code": wrong, "password": PASSWORD}
        )
        assert resp.status_code == 400 and resp.json()["detail"] == "invalid_code"
    # Five wrong guesses: even the right code no longer works; a new one must be asked for.
    assert (
        client.post(
            "/api/v1/auth/verify-email", json={"email": "ada@example.com", "code": code, "password": PASSWORD}
        ).status_code
        == 400
    )


def test_an_expired_code_is_refused(client: TestClient, seeded: Session) -> None:
    client.post("/api/v1/auth/register", json={"email": "ada@example.com", "password": PASSWORD})
    code = client.outbox.last_code("ada@example.com")
    stored = seeded.scalar(select(EmailCode).where(EmailCode.email == "ada@example.com"))
    stored.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    seeded.flush()
    assert (
        client.post(
            "/api/v1/auth/verify-email", json={"email": "ada@example.com", "code": code, "password": PASSWORD}
        ).status_code
        == 400
    )


def test_codes_are_stored_only_as_hashes(client: TestClient, seeded: Session) -> None:
    client.post("/api/v1/auth/register", json={"email": "ada@example.com", "password": PASSWORD})
    code = client.outbox.last_code("ada@example.com")
    stored = seeded.scalar(select(EmailCode).where(EmailCode.email == "ada@example.com"))
    assert code not in stored.code_hash and len(stored.code_hash) == 64


def test_code_emails_are_limited(client: TestClient) -> None:
    client.post("/api/v1/auth/register", json={"email": "ada@example.com", "password": PASSWORD})
    resend = client.post("/api/v1/auth/resend-code", json={"email": "ada@example.com"})
    assert resend.status_code == 429 and resend.headers["Retry-After"]  # a minute apart
    assert len(client.outbox.sent) == 1


def test_resending_answers_the_same_for_unknown_addresses(client: TestClient) -> None:
    resp = client.post("/api/v1/auth/resend-code", json={"email": "nobody@example.com"})
    assert resp.status_code == 202 and client.outbox.sent == []


def test_signing_up_again_before_confirming_sends_a_new_code(client: TestClient) -> None:
    client.post("/api/v1/auth/register", json={"email": "ada@example.com", "password": "first-password"})
    first = client.outbox.last_code("ada@example.com")
    reset_all_limiters()  # past the minute between code emails
    client.post("/api/v1/auth/register", json={"email": "ada@example.com", "password": PASSWORD})
    second = client.outbox.last_code("ada@example.com")
    if first != second:  # (one in a million they match)
        assert (
            client.post(
                "/api/v1/auth/verify-email", json={"email": "ada@example.com", "code": first, "password": PASSWORD}
            ).status_code
            == 400
        )
    assert (
        client.post(
            "/api/v1/auth/verify-email", json={"email": "ada@example.com", "code": second, "password": PASSWORD}
        ).status_code
        == 200
    )
    assert login(client, "ada@example.com").status_code == 200  # with the second password
    assert login(client, "ada@example.com", "first-password").status_code == 401


def test_register_rejects_duplicate_email_in_any_case(client: TestClient) -> None:
    register(client, "ada@example.com")
    resp = client.post("/api/v1/auth/register", json={"email": "ADA@example.com", "password": PASSWORD})
    assert resp.status_code == 409


def test_register_validates_input(client: TestClient) -> None:
    assert client.post("/api/v1/auth/register", json={"email": "not-an-email", "password": PASSWORD}).status_code == 422
    assert client.post("/api/v1/auth/register", json={"email": "a@example.com", "password": "short"}).status_code == 422


def test_throwaway_addresses_cannot_sign_up(client: TestClient) -> None:
    for email in ("ada@mailinator.com", "ada@inbox.yopmail.com"):
        resp = client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})
        assert resp.status_code == 422 and resp.json()["detail"] == "disposable_email"
    assert client.outbox.sent == []


def test_login(client: TestClient) -> None:
    register(client, "ada@example.com")
    ok = login(client, "Ada@example.com")
    assert ok.status_code == 200
    assert ok.json()["access_token"]

    wrong_password = login(client, "ada@example.com", "nope-nope")
    unknown_email = login(client, "who@example.com")
    assert wrong_password.status_code == unknown_email.status_code == 401
    # Same answer either way, so the endpoint can't be used to find out who has an account.
    assert wrong_password.json() == unknown_email.json()


def test_an_account_from_before_codes_confirms_at_its_next_login(client: TestClient, seeded: Session) -> None:
    seeded.add(User(email="old@example.com", hashed_password=hash_password(PASSWORD)))
    seeded.flush()
    resp = login(client, "old@example.com")
    assert resp.status_code == 403 and resp.json()["detail"] == "email_not_verified"
    code = client.outbox.last_code("old@example.com")
    assert (
        client.post(
            "/api/v1/auth/verify-email", json={"email": "old@example.com", "code": code, "password": PASSWORD}
        ).status_code
        == 200
    )
    # A wrong password on such an account says nothing about it and sends nothing.
    assert login(client, "old@example.com", "nope-nope").status_code == 401


def test_a_forgotten_password_is_reset_with_a_code(client: TestClient) -> None:
    register(client, "ada@example.com")
    reset_all_limiters()
    resp = client.post("/api/v1/auth/forgot-password", json={"email": "ada@example.com", "lang": "en"})
    assert resp.status_code == 202
    code = client.outbox.last_code("ada@example.com")
    assert "reset" in client.outbox.sent[-1][1]
    new_password = "a-brand-new-password"
    resp = client.post(
        "/api/v1/auth/reset-password", json={"email": "ada@example.com", "code": code, "password": new_password}
    )
    assert resp.status_code == 200 and resp.json()["access_token"]
    assert login(client, "ada@example.com", new_password).status_code == 200
    assert login(client, "ada@example.com").status_code == 401  # the old one is gone


def test_a_sign_up_code_does_not_reset_a_password(client: TestClient) -> None:
    client.post("/api/v1/auth/register", json={"email": "ada@example.com", "password": PASSWORD})
    code = client.outbox.last_code("ada@example.com")
    resp = client.post(
        "/api/v1/auth/reset-password", json={"email": "ada@example.com", "code": code, "password": "x" * 12}
    )
    assert resp.status_code == 400


def test_forgot_password_answers_the_same_for_unknown_addresses(client: TestClient) -> None:
    resp = client.post("/api/v1/auth/forgot-password", json={"email": "nobody@example.com"})
    assert resp.status_code == 202 and client.outbox.sent == []


def test_me_requires_a_valid_token(client: TestClient) -> None:
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-token"}).status_code == 401


# --- saved routes ------------------------------------------------------------------------------


def test_save_list_open_and_delete_a_route(client: TestClient) -> None:
    auth = register(client, "ada@example.com")
    plan = make_plan(client)
    stop_count = sum(len(d["stops"]) for d in plan["days"])

    saved = client.post("/api/v1/routes", json={"plan": plan}, headers=auth)
    assert saved.status_code == 201, saved.text
    route = saved.json()
    assert route["name"] == "Test City · 2 days"  # default name
    assert route["stop_count"] == stop_count
    assert route["plan"] == plan  # the snapshot comes back exactly as saved

    listed = client.get("/api/v1/routes", headers=auth).json()
    assert [(r["id"], r["stop_count"]) for r in listed] == [(route["id"], stop_count)]

    opened = client.get(f"/api/v1/routes/{route['id']}", headers=auth)
    assert opened.status_code == 200
    assert opened.json()["plan"] == plan

    assert client.delete(f"/api/v1/routes/{route['id']}", headers=auth).status_code == 204
    assert client.get(f"/api/v1/routes/{route['id']}", headers=auth).status_code == 404
    assert client.get("/api/v1/routes", headers=auth).json() == []


def test_save_uses_a_custom_name(client: TestClient) -> None:
    auth = register(client, "ada@example.com")
    resp = client.post("/api/v1/routes", json={"name": "  Honeymoon  ", "plan": make_plan(client)}, headers=auth)
    assert resp.json()["name"] == "Honeymoon"


def test_saved_routes_are_private(client: TestClient) -> None:
    ada = register(client, "ada@example.com")
    bob = register(client, "bob@example.com")
    route_id = client.post("/api/v1/routes", json={"plan": make_plan(client)}, headers=ada).json()["id"]

    assert client.get("/api/v1/routes", headers=bob).json() == []
    assert client.get(f"/api/v1/routes/{route_id}", headers=bob).status_code == 404
    assert client.delete(f"/api/v1/routes/{route_id}", headers=bob).status_code == 404
    assert client.get(f"/api/v1/routes/{route_id}", headers=ada).status_code == 200  # still there


def test_saved_route_endpoints_require_login(client: TestClient) -> None:
    assert client.post("/api/v1/routes", json={"plan": make_plan(client)}).status_code == 401
    assert client.get("/api/v1/routes").status_code == 401


def test_save_rejects_places_outside_the_city(client: TestClient) -> None:
    auth = register(client, "ada@example.com")
    plan = make_plan(client)
    plan["days"][0]["stops"][0]["poi_id"] = "not-a-real-poi"
    resp = client.post("/api/v1/routes", json={"plan": plan}, headers=auth)
    assert resp.status_code == 422
    assert "not-a-real-poi" in resp.text


def test_someone_else_signing_up_with_your_address_cannot_take_the_account(client: TestClient) -> None:
    # Ada starts signing up; before she enters her code, Mallory signs up with Ada's address.
    client.post("/api/v1/auth/register", json={"email": "ada@example.com", "password": PASSWORD})
    reset_all_limiters()
    mallory = "mallorys-password"
    client.post("/api/v1/auth/register", json={"email": "ada@example.com", "password": mallory})
    # Ada gets the newest code by email and enters it, with her own password: it doesn't fit.
    code = client.outbox.last_code("ada@example.com")
    body = {"email": "ada@example.com", "code": code, "password": PASSWORD}
    assert client.post("/api/v1/auth/verify-email", json=body).status_code == 400
    # And Mallory can't log in: the account's password never became hers.
    assert login(client, "ada@example.com", mallory).status_code == 401
    # Ada signs up again and gets in with her password.
    reset_all_limiters()
    assert sign_up(client, "ada@example.com", PASSWORD)
    assert login(client, "ada@example.com", mallory).status_code == 401


def test_a_code_without_the_right_password_does_not_open_the_account(client: TestClient) -> None:
    client.post("/api/v1/auth/register", json={"email": "ada@example.com", "password": PASSWORD})
    code = client.outbox.last_code("ada@example.com")
    body = {"email": "ada@example.com", "code": code, "password": "not-the-password"}
    assert client.post("/api/v1/auth/verify-email", json=body).status_code == 400
    # The code itself still works with the right password (that try was counted, though).
    body["password"] = PASSWORD
    assert client.post("/api/v1/auth/verify-email", json=body).status_code == 200


def test_code_requests_answer_alike_for_known_and_unknown_addresses(client: TestClient) -> None:
    register(client, "ada@example.com")
    reset_all_limiters()
    for email in ("ada@example.com", "nobody@example.com"):
        first = client.post("/api/v1/auth/forgot-password", json={"email": email})
        second = client.post("/api/v1/auth/forgot-password", json={"email": email})
        assert (first.status_code, second.status_code) == (202, 429), email

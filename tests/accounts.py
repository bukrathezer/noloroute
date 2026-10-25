"""Signing up in tests: the emailed code is caught by FakeEmailSender instead of being sent."""

import re

from fastapi.testclient import TestClient

PASSWORD = "s3cure-enough-password"


class FakeEmailSender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []  # to, subject, text

    def send(self, to: str, subject: str, text: str, html: str) -> None:
        self.sent.append((to, subject, text))

    def close(self) -> None:
        pass

    def last_code(self, to: str) -> str:
        texts = [text for address, _, text in self.sent if address == to]
        assert texts, f"no email to {to}"
        match = re.search(r"\b(\d{6})\b", texts[-1])
        assert match, texts[-1]
        return match.group(1)


def sign_up(client: TestClient, email: str = "ada@example.com", password: str = PASSWORD) -> dict[str, str]:
    """Register and confirm the address with the emailed code; returns the auth header."""
    resp = client.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert resp.status_code == 202, resp.text
    outbox: FakeEmailSender = client.outbox  # type: ignore[attr-defined]
    body = {"email": email, "code": outbox.last_code(email), "password": password}
    verified = client.post("/api/v1/auth/verify-email", json=body)
    assert verified.status_code == 200, verified.text
    return {"Authorization": f"Bearer {verified.json()['access_token']}"}

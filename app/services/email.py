"""Sending the account emails: the sign-up code and the password-reset code.

Resend (resend.com) delivers them from the noloroute.com domain. Without an API key (local
development) the email is written to the log instead, code included.
"""

import logging
from html import escape
from typing import Literal, Protocol

import httpx

logger = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"
Purpose = Literal["verify", "reset"]


class EmailError(Exception):
    pass


class EmailSender(Protocol):
    def send(self, to: str, subject: str, text: str, html: str) -> None: ...


class ResendSender:
    def __init__(self, api_key: str, sender: str, timeout: float = 10.0, transport: httpx.BaseTransport | None = None):
        # `transport` lets tests answer requests without the network.
        self._http = httpx.Client(timeout=timeout, headers={"Authorization": f"Bearer {api_key}"}, transport=transport)
        self._sender = sender

    def send(self, to: str, subject: str, text: str, html: str) -> None:
        body = {"from": self._sender, "to": [to], "subject": subject, "text": text, "html": html}
        try:
            resp = self._http.post(RESEND_URL, json=body)
        except httpx.HTTPError as exc:
            raise EmailError(f"request failed: {exc}") from exc
        if resp.is_error:
            raise EmailError(f"HTTP {resp.status_code}: {resp.text[:300]}")

    def close(self) -> None:
        self._http.close()


class LogSender:
    """For development without a Resend key: the email goes to the log."""

    def send(self, to: str, subject: str, text: str, html: str) -> None:
        logger.warning("Email not sent (no RESEND_API_KEY) to %s: %s\n%s", to, subject, text)

    def close(self) -> None:
        pass


TEXTS = {
    "tr": {
        "verify": ("NoloRoute doğrulama kodun: {code}", "Hesabını açmak için bu kodu gir:"),
        "reset": ("NoloRoute şifre sıfırlama kodun: {code}", "Şifreni sıfırlamak için bu kodu gir:"),
        "expires": "Kod {minutes} dakika geçerli.",
        "ignore": "Bu isteği sen yapmadıysan bu e-postayı yok sayabilirsin; hesabında bir şey değişmez.",
    },
    "en": {
        "verify": ("Your NoloRoute code: {code}", "Enter this code to create your account:"),
        "reset": ("Your NoloRoute password reset code: {code}", "Enter this code to reset your password:"),
        "expires": "The code is valid for {minutes} minutes.",
        "ignore": "If you didn't ask for this, you can ignore this email; nothing changes on your account.",
    },
}


def code_email(code: str, purpose: Purpose, lang: str, minutes: int) -> tuple[str, str, str]:
    """The subject, plain text and HTML of a code email."""
    t = TEXTS.get(lang, TEXTS["en"])
    subject, lead = t[purpose]
    subject = subject.format(code=code)
    expires = t["expires"].format(minutes=minutes)
    text = f"{lead}\n\n{code}\n\n{expires}\n{t['ignore']}\n\nNoloRoute · https://noloroute.com"
    html = f"""<!doctype html>
<html lang="{escape(lang)}">
<body style="margin:0;padding:24px;background:#f5f7fb;font-family:Inter,Segoe UI,Arial,sans-serif;color:#0f172a">
  <div style="max-width:440px;margin:0 auto;padding:28px;background:#fff;border:1px solid #dde3ee;border-radius:16px">
    <p style="margin:0 0 16px;font-size:18px;font-weight:700">NoloRoute</p>
    <p style="margin:0 0 16px;font-size:15px">{escape(lead)}</p>
    <p style="margin:0 0 16px;font-size:32px;font-weight:800;letter-spacing:6px;color:#2563eb">{escape(code)}</p>
    <p style="margin:0 0 8px;font-size:14px;color:#5b6478">{escape(expires)}</p>
    <p style="margin:0;font-size:13px;color:#5b6478">{escape(t["ignore"])}</p>
  </div>
</body>
</html>"""
    return subject, text, html

"""Password hashing and login tokens (JWT).

Passwords: never stored, only an Argon2 hash of them. Argon2 is deliberately slow and
memory-hungry, so guessing passwords from a leaked database is expensive; each hash also
embeds a random salt, so two users with the same password get different hashes.

Tokens: after login the client gets a JWT, a signed "ticket" holding the user id and an
expiry time. The server checks the signature (made with JWT_SECRET_KEY) on every request
instead of looking up a session, so a forged or edited token is rejected.
"""

from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash

from app.core.config import get_settings

ALGORITHM = "HS256"

_password_hash = PasswordHash.recommended()  # Argon2id with current recommended parameters
# Checked when a login email doesn't exist, so that case takes as long as a wrong password
# and response times don't reveal which emails are registered.
_DUMMY_HASH = _password_hash.hash("dummy-password-for-timing")


class InvalidTokenError(Exception):
    pass


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if password_hash is None:
        _password_hash.verify(password, _DUMMY_HASH)
        return False
    return _password_hash.verify(password, password_hash)


def create_access_token(user_id: str, now: datetime | None = None) -> str:
    settings = get_settings()
    issued_at = now or datetime.now(UTC)
    payload = {
        "sub": user_id,
        "iat": issued_at,
        "exp": issued_at + timedelta(minutes=settings.access_token_ttl_minutes),
    }
    return jwt.encode(payload, _secret_key(), algorithm=ALGORITHM)


def decode_access_token(token: str) -> str:
    """Return the user id in a valid token; raise InvalidTokenError otherwise (bad signature, expired...)."""
    try:
        payload = jwt.decode(token, _secret_key(), algorithms=[ALGORITHM], options={"require": ["sub", "exp"]})
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from exc
    return payload["sub"]


def _secret_key() -> str:
    key = get_settings().jwt_secret_key
    if not key:
        raise RuntimeError("JWT_SECRET_KEY is not configured")
    return key

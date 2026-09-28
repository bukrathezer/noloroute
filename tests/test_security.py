import base64
import json
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.security import (
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_password_hash_is_salted_argon2_and_verifiable() -> None:
    first, second = hash_password("correct horse battery"), hash_password("correct horse battery")
    assert first.startswith("$argon2id$")
    assert first != second  # random salt per hash
    assert "correct horse" not in first
    assert verify_password("correct horse battery", first)
    assert not verify_password("wrong password", first)


def test_verify_password_without_a_stored_hash_fails() -> None:
    assert not verify_password("anything", None)


def test_token_round_trip() -> None:
    assert decode_access_token(create_access_token("user-1")) == "user-1"


def test_expired_token_is_rejected() -> None:
    issued_long_ago = datetime.now(UTC) - timedelta(days=30)
    with pytest.raises(InvalidTokenError):
        decode_access_token(create_access_token("user-1", now=issued_long_ago))


def test_edited_token_is_rejected() -> None:
    header, _payload, signature = create_access_token("user-1").split(".")
    # Swap in a payload claiming to be someone else but keep the original signature.
    exp = int((datetime.now(UTC) + timedelta(hours=1)).timestamp())
    forged = base64.urlsafe_b64encode(json.dumps({"sub": "admin", "exp": exp}).encode()).rstrip(b"=").decode()
    with pytest.raises(InvalidTokenError):
        decode_access_token(f"{header}.{forged}.{signature}")


def test_token_signed_with_another_key_is_rejected() -> None:
    exp = datetime.now(UTC) + timedelta(hours=1)
    token = jwt.encode({"sub": "user-1", "exp": exp}, "an-attackers-own-secret-key-0123456789", algorithm="HS256")
    with pytest.raises(InvalidTokenError):
        decode_access_token(token)


def test_unsigned_token_is_rejected() -> None:
    # The classic "alg: none" trick: a token with no signature at all.
    exp = datetime.now(UTC) + timedelta(hours=1)
    token = jwt.encode({"sub": "user-1", "exp": exp}, key=None, algorithm="none")
    with pytest.raises(InvalidTokenError):
        decode_access_token(token)

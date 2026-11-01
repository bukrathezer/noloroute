"""Signing in with Google: checking the ID token that Google's sign-in button hands the browser.

The token is a JWT signed by Google. It is genuine only if its signature checks out with Google's
published keys, it was issued for this app's client id, by Google, and hasn't expired; and it
names a Google account whose email Google has confirmed. Only then is the account's id ("sub")
and email used.
"""

from dataclasses import dataclass

import jwt

GOOGLE_CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}
# Google's own addresses: for these Google is the mail provider, not just someone who once checked them.
GOOGLE_MAIL_DOMAINS = {"gmail.com", "googlemail.com"}
CLOCK_LEEWAY_SECONDS = 60  # our clock and Google's may differ a little


class GoogleTokenError(Exception):
    """The token isn't a valid Google sign-in for this app."""


class GoogleUnavailableError(Exception):
    """Google's keys couldn't be fetched to check the token."""


@dataclass(frozen=True)
class GoogleIdentity:
    sub: str  # Google's id for the account: stays the same if its email changes
    email: str
    # Whether Google runs this mailbox (Gmail, or a Workspace domain the token names): only then may
    # the sign-in take over an existing account of that address. A Google account can also be made
    # for any other address, confirmed once, possibly long ago.
    authoritative: bool = False


def is_authoritative(email: str, hosted_domain: str | None) -> bool:
    domain = email.rsplit("@", 1)[-1].lower()
    return domain in GOOGLE_MAIL_DOMAINS or (hosted_domain is not None and domain == hosted_domain.lower())


class GoogleVerifier:
    def __init__(self, client_id: str, certs_url: str = GOOGLE_CERTS_URL) -> None:
        self.client_id = client_id
        # Keeps Google's key set for an hour, then fetches it again: a key Google withdraws stops
        # being trusted within the hour (no per-key cache that would keep it for good).
        self._keys = jwt.PyJWKClient(certs_url, cache_keys=False, lifespan=60 * 60, timeout=10)

    def verify(self, credential: str) -> GoogleIdentity:
        try:
            key = self._keys.get_signing_key_from_jwt(credential)
        except jwt.PyJWKClientConnectionError as exc:
            raise GoogleUnavailableError(str(exc)) from exc
        except jwt.PyJWTError as exc:
            raise GoogleTokenError(str(exc)) from exc
        return identity_from_token(credential, key.key, self.client_id)


def identity_from_token(credential: str, key: object, client_id: str) -> GoogleIdentity:
    """Check a Google ID token against one of Google's public keys (split out for tests)."""
    try:
        claims = jwt.decode(
            credential,
            key,
            algorithms=["RS256"],
            audience=client_id,
            leeway=CLOCK_LEEWAY_SECONDS,
            options={"require": ["iss", "aud", "sub", "exp", "iat"]},
        )
    except jwt.PyJWTError as exc:
        raise GoogleTokenError(str(exc)) from exc
    if claims["iss"] not in GOOGLE_ISSUERS:
        raise GoogleTokenError("not issued by Google")
    email = claims.get("email")
    if not isinstance(email, str) or not email or claims.get("email_verified") is not True:
        raise GoogleTokenError("no confirmed email")
    email = email.strip().lower()
    hosted_domain = claims.get("hd") if isinstance(claims.get("hd"), str) else None
    return GoogleIdentity(sub=str(claims["sub"]), email=email, authoritative=is_authoritative(email, hosted_domain))

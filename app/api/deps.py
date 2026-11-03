from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import InvalidTokenError, token_claims
from app.db.session import get_db
from app.models import User

# Reads "Authorization: Bearer <token>". tokenUrl also powers the "Authorize" button in /docs.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(token: Annotated[str, Depends(oauth2_scheme)], db: DbSession) -> User:
    """Dependency for protected endpoints: the logged-in user, or 401."""
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        user_id, issued_at = token_claims(token)
    except InvalidTokenError:
        raise unauthorized from None
    user = db.get(User, user_id)
    if user is None:  # e.g. the account was deleted after the token was issued
        raise unauthorized
    # Issued before a password reset: that login is over.
    if user.tokens_valid_after is not None and issued_at < user.tokens_valid_after:
        raise unauthorized
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def is_admin(user: User) -> bool:
    """A confirmed account whose address is in ADMIN_EMAILS."""
    admins = {e.strip().lower() for e in get_settings().admin_emails.split(",") if e.strip()}
    return user.email_verified_at is not None and user.email in admins


def get_current_admin(user: CurrentUser) -> User:
    """Dependency for the admin page: an admin, or 404 (so the page's existence isn't revealed)."""
    if not is_admin(user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
    return user


CurrentAdmin = Annotated[User, Depends(get_current_admin)]

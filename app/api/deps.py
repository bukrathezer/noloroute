from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.security import InvalidTokenError, decode_access_token
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
        user_id = decode_access_token(token)
    except InvalidTokenError:
        raise unauthorized from None
    user = db.get(User, user_id)
    if user is None:  # e.g. the account was deleted after the token was issued
        raise unauthorized
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]

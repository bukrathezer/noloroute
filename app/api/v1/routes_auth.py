from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, DbSession
from app.core.rate_limit import RateLimiter, client_ip, limit_by_ip, too_many_requests
from app.core.security import create_access_token, hash_password, verify_password
from app.models import User
from app.schemas.auth import DeleteAccountRequest, RegisterRequest, TokenResponse, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])

# Brute-force protection: attempts per client IP, and wrong passwords per account.
LOGIN_ATTEMPTS_PER_IP = RateLimiter(limit=20, window_seconds=10 * 60)
FAILED_LOGINS_PER_EMAIL = RateLimiter(limit=10, window_seconds=15 * 60)
REGISTRATIONS_PER_IP = RateLimiter(limit=10, window_seconds=60 * 60)


def _token_response(user: User) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user.id),
        user=UserOut(id=user.id, email=user.email, created_at=user.created_at),
    )


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(limit_by_ip(REGISTRATIONS_PER_IP))],
)
def register(req: RegisterRequest, db: DbSession) -> TokenResponse:
    """Create an account and log it in straight away."""
    user = User(email=req.email, hashed_password=hash_password(req.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:  # unique email constraint
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists") from None
    db.refresh(user)
    return _token_response(user)


@router.post("/login", response_model=TokenResponse, dependencies=[Depends(limit_by_ip(LOGIN_ATTEMPTS_PER_IP))])
def login(form: Annotated[OAuth2PasswordRequestForm, Depends()], db: DbSession) -> TokenResponse:
    """OAuth2 password flow: form fields `username` (the email) and `password`."""
    email = form.username.strip().lower()
    # Checked before the password so a locked account can't be probed further.
    if (wait := FAILED_LOGINS_PER_EMAIL.retry_after(email)) is not None:
        raise too_many_requests(wait)

    user = db.scalar(select(User).where(User.email == email))
    # Same message (and similar timing) whether the email or the password is wrong.
    if not verify_password(form.password, user.hashed_password if user else None):
        FAILED_LOGINS_PER_EMAIL.record(email)
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _token_response(user)


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return UserOut(id=user.id, email=user.email, created_at=user.created_at)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(req: DeleteAccountRequest, request: Request, user: CurrentUser, db: DbSession) -> Response:
    """Permanently delete the account and all its saved routes. Asks for the password again."""
    # Counted like a login, so a stolen token can't be used to guess the password.
    if (wait := LOGIN_ATTEMPTS_PER_IP.hit(client_ip(request))) is not None:
        raise too_many_requests(wait)
    if not verify_password(req.password, user.hashed_password):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Incorrect password")
    db.delete(user)  # saved routes and their stops cascade
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

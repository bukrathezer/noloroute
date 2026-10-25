"""Accounts: sign-up with an emailed code, login, password reset, deleting the account.

Signing up emails a six-digit code; the account opens (and takes the password chosen) only once
the code comes back with that password, proving the address is its owner's. Forgotten passwords
are reset the same way. Codes last CODE_TTL_MINUTES, allow MAX_CODE_ATTEMPTS tries, and are stored
only as keyed hashes. Endpoints that take any address answer the same whether or not it has an
account (the emails go out in the background), so they can't tell who has one.
"""

import hmac
import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, DbSession
from app.core.rate_limit import RateLimiter, client_ip, limit_by_ip, too_many_requests
from app.core.security import create_access_token, hash_email_code, hash_password, new_email_code, verify_password
from app.models import EmailCode, User
from app.schemas.auth import (
    CodeSentResponse,
    DeleteAccountRequest,
    ForgotPasswordRequest,
    RegisterRequest,
    ResendCodeRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserOut,
    VerifyEmailRequest,
)
from app.services.disposable_email import is_disposable
from app.services.email import EmailError, EmailSender, code_email

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)

Purpose = Literal["verify", "reset"]
CODE_TTL_MINUTES = 15
MAX_CODE_ATTEMPTS = 5

# Brute-force protection: attempts per client IP, and wrong passwords per account.
LOGIN_ATTEMPTS_PER_IP = RateLimiter(limit=20, window_seconds=10 * 60)
FAILED_LOGINS_PER_EMAIL = RateLimiter(limit=10, window_seconds=15 * 60)
REGISTRATIONS_PER_IP = RateLimiter(limit=10, window_seconds=60 * 60)
# Code emails: a minute apart (per kind) and five an hour per address, so no mailbox gets flooded;
# per client; and in all, under Resend's free 100 a day.
CODE_EMAIL_GAP = RateLimiter(limit=1, window_seconds=60)
CODE_EMAILS_PER_ADDRESS = RateLimiter(limit=5, window_seconds=60 * 60)
CODE_EMAILS_PER_IP = RateLimiter(limit=20, window_seconds=60 * 60)
CODE_EMAILS_PER_DAY = RateLimiter(limit=90, window_seconds=24 * 60 * 60)
# Tries at codes, per client and per address (on top of each code's own MAX_CODE_ATTEMPTS).
CODE_CHECKS_PER_IP = RateLimiter(limit=30, window_seconds=10 * 60)
CODE_CHECKS_PER_ADDRESS = RateLimiter(limit=10, window_seconds=60 * 60)


def get_email_sender(request: Request) -> EmailSender:
    return request.app.state.email_sender


Sender = Annotated[EmailSender, Depends(get_email_sender)]


def _token_response(user: User) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user.id),
        user=UserOut(id=user.id, email=user.email, created_at=user.created_at),
    )


def _email_limits(request: Request, email: str, purpose: Purpose) -> list[tuple[RateLimiter, str]]:
    return [
        (CODE_EMAIL_GAP, f"{purpose}:{email}"),  # a reset code may follow a sign-up code at once
        (CODE_EMAILS_PER_ADDRESS, email),
        (CODE_EMAILS_PER_IP, client_ip(request)),
        (CODE_EMAILS_PER_DAY, "all"),
    ]


def _check_email_limits(request: Request, email: str, purpose: Purpose) -> None:
    """429 if a code email to this address may not go yet. Records the request: called for every
    address alike, existing or not, so the answer tells nothing about accounts."""
    limits = _email_limits(request, email, purpose)
    for limiter, key in limits:
        if (wait := limiter.retry_after(key)) is not None:
            raise too_many_requests(wait)
    for limiter, key in limits:
        limiter.record(key)


def _send_code(
    db: Session,
    sender: EmailSender,
    tasks: BackgroundTasks | None,
    email: str,
    purpose: Purpose,
    lang: str,
    pending_password_hash: str | None = None,
) -> None:
    """Replace the address's code for `purpose` with a new one; it is emailed after the response
    (`tasks`), or right away without it, as when the response is an error (background tasks
    don't run then).

    The limits must have been checked (_check_email_limits).
    """
    code = new_email_code()
    now = datetime.now(UTC)
    db.execute(delete(EmailCode).where(EmailCode.expires_at < now))  # tidy up old ones on the way
    db.execute(delete(EmailCode).where(EmailCode.email == email, EmailCode.purpose == purpose))
    db.add(
        EmailCode(
            email=email,
            purpose=purpose,
            code_hash=hash_email_code(code, email, purpose),
            pending_password_hash=pending_password_hash,
            expires_at=now + timedelta(minutes=CODE_TTL_MINUTES),
        )
    )
    try:
        db.commit()
    except IntegrityError:  # another request for the same address at the same moment
        db.rollback()
        raise too_many_requests(60) from None
    subject, text, html = code_email(code, purpose, lang, CODE_TTL_MINUTES)
    if tasks is None:
        _deliver(sender, email, subject, text, html)
    else:
        tasks.add_task(_deliver, sender, email, subject, text, html)


def _deliver(sender: EmailSender, email: str, subject: str, text: str, html: str) -> None:
    try:
        sender.send(email, subject, text, html)
    except EmailError:
        logger.exception("Couldn't email a code to %s", email)


def _use_code(db: Session, request: Request, email: str, purpose: Purpose, code: str) -> EmailCode:
    """Use up the address's current code for `purpose` if `code` is it; else 400 "invalid_code".

    Every try counts against the code first, in one database statement, so tries sent side by
    side can't get past MAX_CODE_ATTEMPTS.
    """
    for limiter, key in ((CODE_CHECKS_PER_IP, client_ip(request)), (CODE_CHECKS_PER_ADDRESS, email)):
        if (wait := limiter.hit(key)) is not None:
            raise too_many_requests(wait)
    invalid = HTTPException(status.HTTP_400_BAD_REQUEST, "invalid_code")
    stored = db.execute(
        update(EmailCode)
        .where(
            EmailCode.email == email,
            EmailCode.purpose == purpose,
            EmailCode.attempts < MAX_CODE_ATTEMPTS,
            EmailCode.expires_at > datetime.now(UTC),
        )
        .values(attempts=EmailCode.attempts + 1)
        .returning(EmailCode)
    ).scalar_one_or_none()
    db.commit()
    if stored is None or not hmac.compare_digest(stored.code_hash, hash_email_code(code, email, purpose)):
        raise invalid
    # Only one request gets to use it.
    if db.execute(delete(EmailCode).where(EmailCode.id == stored.id)).rowcount != 1:
        raise invalid
    return stored


@router.post(
    "/register",
    response_model=CodeSentResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(limit_by_ip(REGISTRATIONS_PER_IP))],
)
def register(
    req: RegisterRequest, request: Request, tasks: BackgroundTasks, db: DbSession, sender: Sender
) -> CodeSentResponse:
    """Start a sign-up: a code goes to the address; verify-email with it (and the same password)
    opens the account. Signing up again before that sends a new code for the new password; an
    unconfirmed account's password itself changes only when a code confirms it."""
    if is_disposable(req.email):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "disposable_email")
    user = db.scalar(select(User).where(User.email == req.email))
    if user is not None and user.email_verified_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")
    _check_email_limits(request, req.email, "verify")
    hashed = hash_password(req.password)
    if user is None:
        db.add(User(email=req.email, hashed_password=hashed))
    _send_code(db, sender, tasks, req.email, "verify", req.lang, pending_password_hash=hashed)
    return CodeSentResponse(email=req.email)


@router.post("/verify-email", response_model=TokenResponse)
def verify_email(req: VerifyEmailRequest, request: Request, db: DbSession) -> TokenResponse:
    """Confirm the address with its code and the password it was asked for with; the account is
    then logged in. (A code someone else asked for, with their password, doesn't fit yours.)"""
    used = _use_code(db, request, req.email, "verify", req.code)
    user = db.scalar(select(User).where(User.email == req.email))
    expected = used.pending_password_hash or (user.hashed_password if user else None)
    if user is None or not verify_password(req.password, expected):
        db.rollback()  # the code stays (its try was counted)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid_code")
    if used.pending_password_hash:
        user.hashed_password = used.pending_password_hash
    user.email_verified_at = datetime.now(UTC)
    db.commit()
    return _token_response(user)


@router.post("/resend-code", response_model=CodeSentResponse, status_code=status.HTTP_202_ACCEPTED)
def resend_code(
    req: ResendCodeRequest, request: Request, tasks: BackgroundTasks, db: DbSession, sender: Sender
) -> CodeSentResponse:
    """A new code for a sign-up still to confirm, or for a password reset. Answers the same
    whether or not such an account exists, so it can't be used to find out who has one."""
    _check_email_limits(request, req.email, req.purpose)
    user = db.scalar(select(User).where(User.email == req.email))
    if user is not None and (req.purpose == "reset" or user.email_verified_at is None):
        # A sign-up code keeps the password it was first asked for with.
        pending = None
        if req.purpose == "verify":
            pending = db.scalar(
                select(EmailCode.pending_password_hash).where(
                    EmailCode.email == req.email, EmailCode.purpose == "verify"
                )
            )
        _send_code(db, sender, tasks, req.email, req.purpose, req.lang, pending_password_hash=pending)
    return CodeSentResponse(email=req.email)


@router.post("/forgot-password", response_model=CodeSentResponse, status_code=status.HTTP_202_ACCEPTED)
def forgot_password(
    req: ForgotPasswordRequest, request: Request, tasks: BackgroundTasks, db: DbSession, sender: Sender
) -> CodeSentResponse:
    """Email a reset code, if the address has an account (the answer is the same either way)."""
    _check_email_limits(request, req.email, "reset")
    if db.scalar(select(User.id).where(User.email == req.email)) is not None:
        _send_code(db, sender, tasks, req.email, "reset", req.lang)
    return CodeSentResponse(email=req.email)


@router.post("/reset-password", response_model=TokenResponse)
def reset_password(req: ResetPasswordRequest, request: Request, db: DbSession) -> TokenResponse:
    """Set a new password with the emailed code; the account is then logged in."""
    _use_code(db, request, req.email, "reset", req.code)
    user = db.scalar(select(User).where(User.email == req.email))
    if user is None:
        db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid_code")
    user.hashed_password = hash_password(req.password)
    user.email_verified_at = user.email_verified_at or datetime.now(UTC)  # the code proved the address
    # A half-finished sign-up's code no longer fits the new password.
    db.execute(delete(EmailCode).where(EmailCode.email == req.email, EmailCode.purpose == "verify"))
    FAILED_LOGINS_PER_EMAIL.forget(req.email)
    db.commit()
    return _token_response(user)


@router.post("/login", response_model=TokenResponse, dependencies=[Depends(limit_by_ip(LOGIN_ATTEMPTS_PER_IP))])
def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()], request: Request, db: DbSession, sender: Sender
) -> TokenResponse:
    """OAuth2 password flow: form fields `username` (the email) and `password`.

    The right password on an unconfirmed account sends it a new code and answers 403
    "email_not_verified" (accounts made before codes existed confirm this way too).
    """
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
    if user.email_verified_at is None:
        # A code sent a moment ago still holds: don't fail the login over the email limits.
        limits = _email_limits(request, email, "verify")
        if all(limiter.retry_after(key) is None for limiter, key in limits):
            for limiter, key in limits:
                limiter.record(key)
            _send_code(db, sender, None, email, "verify", _lang_of(request))  # the password is proven
        raise HTTPException(status.HTTP_403_FORBIDDEN, "email_not_verified")
    return _token_response(user)


def _lang_of(request: Request) -> str:
    """The code email's language for a login (a form post carries none): the browser's."""
    return "tr" if request.headers.get("accept-language", "").lower().startswith("tr") else "en"


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
    db.execute(delete(EmailCode).where(EmailCode.email == user.email))
    db.delete(user)  # saved routes and their stops cascade
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, new_id


class EmailCode(Base):
    """A one-time code sent by email: to confirm an address on sign-up, or to reset a password.

    Only a keyed hash of the code is stored (app/core/security.py), so the table alone can't be
    used to log in. A new code for the same address and purpose replaces the old one.
    """

    __tablename__ = "email_code"
    __table_args__ = (UniqueConstraint("email", "purpose"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String, index=True)
    purpose: Mapped[str] = mapped_column(String(10))  # "verify" or "reset"
    code_hash: Mapped[str] = mapped_column(String(64))
    # A sign-up's password, set on the account only when the code confirms it: signing up again
    # with someone else's unconfirmed address never changes that account's password.
    pending_password_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)  # tries so far
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

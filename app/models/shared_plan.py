from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SharedPlan(Base):
    """A plan shared by link (/p/<id>): a frozen copy that anyone with the link can open, no login."""

    __tablename__ = "shared_plan"

    # Short and random: it is the link, so it must be hard to guess (see new_share_id).
    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    city_id: Mapped[str] = mapped_column(ForeignKey("city.id"))
    # The sharer's page language: the link preview (WhatsApp, Telegram, ...) is written in it.
    lang: Mapped[str] = mapped_column(String(2))
    # Of the language and the plan: sharing the same plan again gives the same link.
    content_hash: Mapped[str] = mapped_column(String(64), unique=True)
    # As the sharer saw it (travel times, street paths), so opening it needs no Routes API calls.
    plan: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # Indexed: sharing stops for the day after MAX_SHARES_PER_DAY (routes_share.py).
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

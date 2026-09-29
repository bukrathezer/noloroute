from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.poi import POI
    from app.models.saved_route import SavedRoute


class City(Base):
    __tablename__ = "city"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)  # English
    name_tr: Mapped[str | None] = mapped_column(String(100), nullable=True)
    country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)  # ISO 3166-1 alpha-2
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    # IANA time zone, e.g. "Europe/Istanbul": transit timetables are looked up in local time.
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, server_default="UTC")
    # Which ticket POI.entry_price is ("adult" or "tr_citizen") and when prices were checked.
    price_basis: Mapped[str | None] = mapped_column(String(20), nullable=True)
    prices_checked_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    # When the ingestion last refreshed this city, and how many Nearby requests that took (the
    # monthly refresh picks the stalest cities that fit its request budget).
    refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_ingest_requests: Mapped[int | None] = mapped_column(Integer, nullable=True)

    pois: Mapped[list["POI"]] = relationship(back_populates="city")
    saved_routes: Mapped[list["SavedRoute"]] = relationship(back_populates="city")

from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.poi import POI
    from app.models.saved_route import SavedRoute


class City(Base):
    __tablename__ = "city"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    # IANA time zone, e.g. "Europe/Istanbul": transit timetables are looked up in local time.
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, server_default="UTC")

    pois: Mapped[list["POI"]] = relationship(back_populates="city")
    saved_routes: Mapped[list["SavedRoute"]] = relationship(back_populates="city")

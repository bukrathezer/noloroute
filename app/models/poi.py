from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, new_id

if TYPE_CHECKING:
    from app.models.city import City
    from app.models.route_stop import RouteStop


class POICategory(StrEnum):
    MUSEUM = "MUSEUM"
    LANDMARK = "LANDMARK"
    PARK = "PARK"
    RELIGIOUS_SITE = "RELIGIOUS_SITE"
    VIEWPOINT = "VIEWPOINT"
    MARKET = "MARKET"
    OTHER = "OTHER"


class POI(Base):
    __tablename__ = "poi"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    city_id: Mapped[str] = mapped_column(ForeignKey("city.id"), index=True)
    place_id: Mapped[str] = mapped_column(String, unique=True)  # Google Place ID, used for dedup
    name: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    google_type: Mapped[str | None] = mapped_column(String(64), nullable=True)  # Places primaryType
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    avg_duration_min: Mapped[int] = mapped_column(Integer)
    entry_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    opening_hours: Mapped[str | None] = mapped_column(String, nullable=True)  # JSON: Places "periods"
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    user_rating_count: Mapped[int | None] = mapped_column(Integer, nullable=True)  # popularity signal
    # A sentence or two from the place's Wikipedia article (CC BY-SA, shown with a link to it),
    # found through its Wikidata item, e.g. "Q91274". Filled by scripts/describe_pois.py.
    wikidata_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    description_tr: Mapped[str | None] = mapped_column(String(300), nullable=True)
    description_en: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # When that lookup last ran, found or not: later runs only look at places added since.
    wiki_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    city: Mapped["City"] = relationship(back_populates="pois")
    route_stops: Mapped[list["RouteStop"]] = relationship(back_populates="poi")

from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Float, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, new_id

if TYPE_CHECKING:
    from app.models.city import City
    from app.models.route_stop import RouteStop


class POI(Base):
    __tablename__ = "poi"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    city_id: Mapped[str] = mapped_column(ForeignKey("city.id"), index=True)
    place_id: Mapped[str] = mapped_column(String, unique=True)  # Google Place ID, used for dedup
    name: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    avg_duration_min: Mapped[int] = mapped_column(Integer)
    entry_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    opening_hours: Mapped[str | None] = mapped_column(String, nullable=True)

    city: Mapped["City"] = relationship(back_populates="pois")
    route_stops: Mapped[list["RouteStop"]] = relationship(back_populates="poi")

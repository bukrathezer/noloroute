from typing import TYPE_CHECKING

from sqlalchemy import Float, ForeignKey, Integer, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.city import City
    from app.models.route_stop import RouteStop
    from app.models.user import User


class SavedRoute(Base):
    __tablename__ = "saved_route"

    id: Mapped[str] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("user.id"))
    city_id: Mapped[str] = mapped_column(ForeignKey("city.id"))
    accommodation_lat: Mapped[float] = mapped_column(Float)
    accommodation_lng: Mapped[float] = mapped_column(Float)
    duration_days: Mapped[int] = mapped_column(Integer)
    budget: Mapped[float | None] = mapped_column(Numeric, nullable=True)

    user: Mapped["User"] = relationship(back_populates="saved_routes")
    city: Mapped["City"] = relationship(back_populates="saved_routes")
    stops: Mapped[list["RouteStop"]] = relationship(
        back_populates="saved_route", order_by="RouteStop.day_number, RouteStop.order_in_day"
    )

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, new_id

if TYPE_CHECKING:
    from app.models.city import City
    from app.models.route_stop import RouteStop
    from app.models.user import User


class SavedRoute(Base):
    __tablename__ = "saved_route"

    id: Mapped[str] = mapped_column(primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(100))
    user_id: Mapped[str] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    city_id: Mapped[str] = mapped_column(ForeignKey("city.id"))
    accommodation_lat: Mapped[float] = mapped_column(Float)
    accommodation_lng: Mapped[float] = mapped_column(Float)
    duration_days: Mapped[int] = mapped_column(Integer)
    budget: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    travel_mode: Mapped[str] = mapped_column(String(10))
    # The plan exactly as the user saw it (travel times, street paths), so reopening it needs no
    # new Routes API calls. RouteStop rows hold the same stops in queryable form.
    plan: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="saved_routes")
    city: Mapped["City"] = relationship(back_populates="saved_routes")
    stops: Mapped[list["RouteStop"]] = relationship(
        back_populates="saved_route",
        order_by="RouteStop.day_number, RouteStop.order_in_day",
        cascade="all, delete-orphan",
    )

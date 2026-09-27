from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.poi import POI
    from app.models.saved_route import SavedRoute


class RouteStop(Base):
    __tablename__ = "route_stop"

    id: Mapped[str] = mapped_column(primary_key=True)
    saved_route_id: Mapped[str] = mapped_column(ForeignKey("saved_route.id"))
    poi_id: Mapped[str] = mapped_column(ForeignKey("poi.id"))
    day_number: Mapped[int] = mapped_column(Integer)
    order_in_day: Mapped[int] = mapped_column(Integer)

    saved_route: Mapped["SavedRoute"] = relationship(back_populates="stops")
    poi: Mapped["POI"] = relationship(back_populates="route_stops")

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, new_id


class PlanLog(Base):
    """One trip planned (for the admin page's counts). Nothing about who planned it: no account,
    no address, no place they stay; just the city, how they get around and for how many days."""

    __tablename__ = "plan_log"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    city_id: Mapped[str] = mapped_column(ForeignKey("city.id"), index=True)
    travel_mode: Mapped[str] = mapped_column(String(10))
    duration_days: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

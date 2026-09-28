from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, new_id

if TYPE_CHECKING:
    from app.models.saved_route import SavedRoute


class User(Base):
    __tablename__ = "user"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)

    saved_routes: Mapped[list["SavedRoute"]] = relationship(back_populates="user", cascade="all, delete-orphan")

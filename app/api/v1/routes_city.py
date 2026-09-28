from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import POI, City
from app.schemas.city import CityOut

router = APIRouter(prefix="/cities", tags=["cities"])


@router.get("", response_model=list[CityOut])
def list_cities(db: Annotated[Session, Depends(get_db)]) -> list[CityOut]:
    rows = db.execute(select(City, func.count(POI.id)).outerjoin(City.pois).group_by(City.id).order_by(City.name)).all()
    return [CityOut(id=city.id, name=city.name, currency_code=city.currency_code, poi_count=n) for city, n in rows]

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import POI, City
from app.schemas.city import CityOut, SightOut
from app.services.route_optimizer import popularity_with_default
from app.services.travel_guide import CONTINENT_OF_COUNTRY

router = APIRouter(prefix="/cities", tags=["cities"])

MAX_SIGHTS = 100


@router.get("", response_model=list[CityOut])
def list_cities(db: Annotated[Session, Depends(get_db)]) -> list[CityOut]:
    rows = db.execute(
        select(City, func.count(POI.id), func.avg(POI.latitude), func.avg(POI.longitude))
        .outerjoin(City.pois)
        .group_by(City.id)
        .order_by(City.name)
    ).all()
    return [
        CityOut(
            id=city.id,
            name=city.name,
            name_tr=city.name_tr,
            country_code=city.country_code,
            continent=CONTINENT_OF_COUNTRY.get(city.country_code or ""),
            currency_code=city.currency_code,
            poi_count=count,
            center_lat=lat,
            center_lng=lng,
        )
        for city, count, lat, lng in rows
    ]


@router.get("/{city_id}/sights", response_model=list[SightOut])
def list_sights(
    city_id: str,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=MAX_SIGHTS)] = 60,
) -> list[SightOut]:
    """The city's best-known sights, most famous first: a preview on the map before planning."""
    if db.get(City, city_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown city")
    pois = db.scalars(select(POI).where(POI.city_id == city_id)).all()
    fame = popularity_with_default(pois)
    # The list changes only when the city is refreshed (monthly).
    response.headers["Cache-Control"] = "public, max-age=3600"
    return [
        SightOut(poi_id=p.id, name=p.name, name_tr=p.name_tr, category=p.category, lat=p.latitude, lng=p.longitude)
        for p in sorted(pois, key=fame, reverse=True)[:limit]
    ]

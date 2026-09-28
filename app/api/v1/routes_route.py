from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import POI, City
from app.schemas.route import RoutePlanRequest, RoutePlanResponse
from app.services.geo import LatLng
from app.services.route_optimizer import HotelTooFarError, plan_trip
from app.services.routes_client import RoutesClient

router = APIRouter(prefix="/routes", tags=["routes"])


def get_routes_client(request: Request) -> RoutesClient | None:
    """The shared Routes API client created at startup; None when no API key is configured."""
    return request.app.state.routes_client


def load_city_pois(db: Session, city_id: str) -> tuple[City | None, list[POI]]:
    city = db.get(City, city_id)
    if city is None:
        return None, []
    return city, list(db.scalars(select(POI).where(POI.city_id == city_id)))


@router.post("/plan", response_model=RoutePlanResponse)
async def plan_route(
    req: RoutePlanRequest,
    db: Annotated[Session, Depends(get_db)],
    routes_client: Annotated[RoutesClient | None, Depends(get_routes_client)],
) -> RoutePlanResponse:
    # SQLAlchemy is synchronous here, so run the query in a worker thread instead of blocking the event loop.
    city, pois = await run_in_threadpool(load_city_pois, db, req.city_id)
    if city is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown city '{req.city_id}'")

    hotel = LatLng(req.accommodation.lat, req.accommodation.lng)
    try:
        days = await plan_trip(pois, hotel, req.duration_days, req.budget, req.travel_mode, routes_client)
    except HotelTooFarError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    prices = [stop.entry_price for day in days for stop in day.stops]
    return RoutePlanResponse(
        city_id=city.id,
        currency_code=city.currency_code,
        travel_mode=req.travel_mode,
        duration_days=req.duration_days,
        total_entry_cost=sum((p for p in prices if p is not None), Decimal(0)),
        unpriced_stop_count=sum(p is None for p in prices),
        days=days,
    )

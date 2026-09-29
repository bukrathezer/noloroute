import asyncio
import logging
from datetime import UTC, date, timedelta, tzinfo
from decimal import Decimal
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, DbSession
from app.core.rate_limit import RateLimiter, client_ip, too_many_requests
from app.db.session import get_db
from app.models import POI, City, RouteStop, SavedRoute, User
from app.schemas.route import DayPlan, RemoveStopRequest, RoutePlanRequest, RoutePlanResponse
from app.schemas.saved_route import SavedRouteOut, SavedRouteSummary, SaveRouteRequest
from app.services.geo import LatLng
from app.services.route_optimizer import HotelTooFarError, build_day, order_day, plan_trip
from app.services.routes_client import RoutesClient, TravelMode
from app.services.weather import DayWeather, WeatherClient, WeatherError

router = APIRouter(prefix="/routes", tags=["routes"])
logger = logging.getLogger(__name__)

# Transit routing is the costliest in Google calls (two route matrices per day), so it is capped
# per client: plans and stop removals together.
TRANSIT_ROUTINGS_PER_IP = RateLimiter(limit=30, window_seconds=60 * 60)


def limit_transit(request: Request, mode: TravelMode) -> None:
    if mode is TravelMode.TRANSIT and (wait := TRANSIT_ROUTINGS_PER_IP.hit(client_ip(request))) is not None:
        raise too_many_requests(wait)


def city_timezone(city: City) -> tzinfo:
    try:
        return ZoneInfo(city.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning("Unknown time zone %r for city %s, using UTC", city.timezone, city.id)
        return UTC


def get_routes_client(request: Request) -> RoutesClient | None:
    """The shared Routes API client created at startup; None when no API key is configured."""
    return request.app.state.routes_client


def get_weather_client(request: Request) -> WeatherClient | None:
    return request.app.state.weather_client


async def fetch_weather(client: WeatherClient | None, where: LatLng, dates: list[date]) -> list[DayWeather] | None:
    """Weather per trip day, or None: a plan never fails just because the weather service does."""
    if client is None:
        return None
    try:
        return await client.for_dates(where, dates)
    except WeatherError as exc:
        logger.warning("Weather unavailable, planning without it: %s", exc)
        return None


def load_city_pois(db: Session, city_id: str) -> tuple[City | None, list[POI]]:
    city = db.get(City, city_id)
    if city is None:
        return None, []
    return city, list(db.scalars(select(POI).where(POI.city_id == city_id)))


@router.post("/plan", response_model=RoutePlanResponse)
async def plan_route(
    req: RoutePlanRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    routes_client: Annotated[RoutesClient | None, Depends(get_routes_client)],
    weather_client: Annotated[WeatherClient | None, Depends(get_weather_client)],
) -> RoutePlanResponse:
    limit_transit(request, req.travel_mode)
    hotel = LatLng(req.accommodation.lat, req.accommodation.lng)
    dates = [req.start_date + timedelta(days=i) for i in range(req.duration_days)] if req.start_date else None
    # The DB query (synchronous SQLAlchemy, so in a worker thread) and the weather lookup run side by side.
    (city, pois), weather = await asyncio.gather(
        run_in_threadpool(load_city_pois, db, req.city_id),
        fetch_weather(weather_client, hotel, dates) if dates else asyncio.sleep(0),
    )
    if city is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown city '{req.city_id}'")

    try:
        days = await plan_trip(
            pois,
            hotel,
            req.duration_days,
            req.budget,
            req.travel_mode,
            routes_client,
            dates=dates,
            weather=weather,
            tz=city_timezone(city),
        )
    except HotelTooFarError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    return RoutePlanResponse(
        city_id=city.id,
        currency_code=city.currency_code,
        accommodation=req.accommodation,
        budget=req.budget,
        travel_mode=req.travel_mode,
        duration_days=req.duration_days,
        start_date=req.start_date,
        days=days,
        price_basis=city.price_basis,
        prices_checked_on=city.prices_checked_on,
        **_plan_totals(days),
    )


@router.post("/plan/remove-stop", response_model=RoutePlanResponse)
async def remove_stop(
    req: RemoveStopRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    routes_client: Annotated[RoutesClient | None, Depends(get_routes_client)],
) -> RoutePlanResponse:
    """Drop one stop from a plan and re-route only the day it was on; other days are untouched."""
    plan = req.plan
    day = next((d for d in plan.days if any(s.poi_id == req.poi_id for s in d.stops)), None)
    if day is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That stop is not in the plan")

    limit_transit(request, plan.travel_mode)
    remaining_ids = [s.poi_id for s in day.stops if s.poi_id != req.poi_id]
    city, pois = await run_in_threadpool(_load_city_and_pois, db, plan.city_id, remaining_ids)
    hotel = LatLng(plan.accommodation.lat, plan.accommodation.lng)
    routed = await order_day(hotel, pois, plan.travel_mode, routes_client, day=day.date, tz=city_timezone(city))
    new_day = build_day(
        day.day_number, pois, routed, day_date=day.date, weather=day.weather, rain_adjusted=day.rain_adjusted
    )
    new_day.dropped_stops = day.dropped_stops + new_day.dropped_stops

    days = [new_day if d.day_number == day.day_number else d for d in plan.days]
    return plan.model_copy(update={"days": days, **_plan_totals(days)})


def _load_city_and_pois(db: Session, city_id: str, poi_ids: list[str]) -> tuple[City, list[POI]]:
    city = db.get(City, city_id)
    if city is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown city '{city_id}'")
    return city, _load_pois(db, city_id, poi_ids)


def _load_pois(db: Session, city_id: str, poi_ids: list[str]) -> list[POI]:
    """The POIs for `poi_ids` in that order; 422 if any isn't a POI of the city."""
    by_id = {poi.id: poi for poi in db.scalars(select(POI).where(POI.id.in_(poi_ids), POI.city_id == city_id))}
    if unknown := set(poi_ids) - by_id.keys():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown places for this city: {sorted(unknown)}")
    return [by_id[i] for i in poi_ids]


def _plan_totals(days: list[DayPlan]) -> dict[str, Decimal | int]:
    prices = [stop.entry_price for day in days for stop in day.stops]
    return {
        "total_entry_cost": sum((p for p in prices if p is not None), Decimal(0)),
        "unpriced_stop_count": sum(p is None for p in prices),
    }


# ---------------------------------------------------------------------------------------------
# Saved routes (require login). Everything is scoped to the current user: another user's route
# answers 404 rather than 403, so its existence isn't revealed.
# ---------------------------------------------------------------------------------------------

MAX_SAVED_ROUTES_LISTED = 100


@router.post("", response_model=SavedRouteOut, status_code=status.HTTP_201_CREATED)
def save_route(req: SaveRouteRequest, user: CurrentUser, db: DbSession) -> SavedRouteOut:
    city = _validated_city(db, req.plan)
    route = SavedRoute(name=(req.name or "").strip() or _default_name(city, req.plan.duration_days), user_id=user.id)
    _apply_plan(route, req.plan)
    db.add(route)
    db.commit()
    db.refresh(route)
    return _saved_route_out(route)


@router.put("/{route_id}", response_model=SavedRouteOut)
def update_saved_route(route_id: str, req: SaveRouteRequest, user: CurrentUser, db: DbSession) -> SavedRouteOut:
    """Replace a saved route's plan (e.g. after removing stops); the name changes only if given."""
    route = _owned_route(db, user, route_id)
    _validated_city(db, req.plan)
    _apply_plan(route, req.plan)
    if name := (req.name or "").strip():
        route.name = name
    db.commit()
    db.refresh(route)
    return _saved_route_out(route)


@router.get("", response_model=list[SavedRouteSummary])
def list_saved_routes(user: CurrentUser, db: DbSession) -> list[SavedRouteSummary]:
    """The current user's saved routes, newest first."""
    rows = db.execute(
        select(SavedRoute, func.count(RouteStop.id))
        .outerjoin(SavedRoute.stops)
        .where(SavedRoute.user_id == user.id)
        .group_by(SavedRoute.id)
        .order_by(SavedRoute.created_at.desc())
        .limit(MAX_SAVED_ROUTES_LISTED)
    ).all()
    return [_summary(route, stop_count) for route, stop_count in rows]


@router.get("/{route_id}", response_model=SavedRouteOut)
def get_saved_route(route_id: str, user: CurrentUser, db: DbSession) -> SavedRouteOut:
    return _saved_route_out(_owned_route(db, user, route_id))


@router.delete("/{route_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_saved_route(route_id: str, user: CurrentUser, db: DbSession) -> Response:
    db.delete(_owned_route(db, user, route_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _owned_route(db: Session, user: User, route_id: str) -> SavedRoute:
    route = db.get(SavedRoute, route_id)
    if route is None or route.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Saved route not found")
    return route


def _validated_city(db: Session, plan: RoutePlanResponse) -> City:
    """The plan comes from the client, so check the city exists and every stop is one of its POIs."""
    city = db.get(City, plan.city_id)
    if city is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown city '{plan.city_id}'")
    poi_ids = {stop.poi_id for day in plan.days for stop in day.stops}
    if not poi_ids:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The plan has no stops")
    _load_pois(db, city.id, sorted(poi_ids))
    return city


def _apply_plan(route: SavedRoute, plan: RoutePlanResponse) -> None:
    route.city_id = plan.city_id
    route.accommodation_lat = plan.accommodation.lat
    route.accommodation_lng = plan.accommodation.lng
    route.duration_days = plan.duration_days
    route.budget = plan.budget
    route.travel_mode = plan.travel_mode.value
    route.plan = plan.model_dump(mode="json")
    # Replacing the list deletes the old rows (delete-orphan cascade).
    route.stops = [
        RouteStop(poi_id=stop.poi_id, day_number=day.day_number, order_in_day=stop.order_in_day)
        for day in plan.days
        for stop in day.stops
    ]


def _default_name(city: City, days: int) -> str:
    return f"{city.name} · {days} {'day' if days == 1 else 'days'}"


def _summary(route: SavedRoute, stop_count: int) -> SavedRouteSummary:
    return SavedRouteSummary(
        id=route.id,
        name=route.name,
        city_id=route.city_id,
        duration_days=route.duration_days,
        travel_mode=route.travel_mode,
        stop_count=stop_count,
        created_at=route.created_at,
    )


def _saved_route_out(route: SavedRoute) -> SavedRouteOut:
    plan = RoutePlanResponse.model_validate(route.plan)
    stop_count = sum(len(day.stops) for day in plan.days)
    return SavedRouteOut(**_summary(route, stop_count).model_dump(), plan=plan)

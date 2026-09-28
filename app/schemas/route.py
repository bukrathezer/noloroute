from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.services.routes_client import TravelMode

MAX_TRIP_DAYS = 7
MAX_STOPS_PER_DAY = 25  # Routes API waypoint-optimization limit


class Coordinates(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class RoutePlanRequest(BaseModel):
    city_id: str = Field(examples=["paris"])
    accommodation: Coordinates = Field(examples=[{"lat": 48.8566, "lng": 2.3522}])
    duration_days: int = Field(ge=1, le=MAX_TRIP_DAYS, examples=[2])
    budget: Decimal | None = Field(
        default=None,
        ge=0,
        description="Max total entry fees, in the city's currency. Omit for no limit.",
        examples=[100],
    )
    travel_mode: TravelMode = TravelMode.DRIVE


class PlannedStop(BaseModel):
    order_in_day: int
    poi_id: str
    name: str
    category: str
    latitude: float
    longitude: float
    visit_minutes: int
    travel_minutes_from_previous: int
    distance_km_from_previous: float
    # Google encoded polyline of the street path from the previous point; None for estimates.
    path_from_previous: str | None
    entry_price: Decimal | None = Field(examples=["17.00"])
    rating: float | None


class DayPlan(BaseModel):
    day_number: int = Field(ge=1, le=MAX_TRIP_DAYS)
    stops: list[PlannedStop] = Field(max_length=MAX_STOPS_PER_DAY)
    return_travel_minutes: int
    return_distance_km: float
    return_path: str | None
    total_travel_minutes: int
    total_visit_minutes: int
    # "google": times from the Routes API; "estimate": straight-line fallback when Google is unavailable.
    routing_source: Literal["google", "estimate"]


class RoutePlanResponse(BaseModel):
    city_id: str
    currency_code: str
    accommodation: Coordinates
    budget: Decimal | None
    travel_mode: TravelMode
    duration_days: int = Field(ge=1, le=MAX_TRIP_DAYS)
    total_entry_cost: Decimal = Field(examples=["34.00"])
    unpriced_stop_count: int = Field(description="Stops whose entry price is unknown (not counted in the cost).")
    days: list[DayPlan] = Field(max_length=MAX_TRIP_DAYS)

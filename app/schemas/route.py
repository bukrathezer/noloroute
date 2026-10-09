import datetime as dt
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.services.routes_client import TravelMode

MAX_TRIP_DAYS = 7
MAX_STOPS_PER_DAY = 25  # Routes API waypoint-optimization limit
MAX_DAYS_AHEAD = 365


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
    start_date: dt.date | None = Field(
        default=None,
        description="Date of day 1. Enables opening hours and weather; omit to plan without dates.",
    )

    @field_validator("start_date")
    @classmethod
    def start_date_in_range(cls, value: dt.date | None) -> dt.date | None:
        # One day of slack for visitors whose "today" is still yesterday in UTC.
        today = dt.date.today()
        if value is not None and not today - dt.timedelta(days=1) <= value <= today + dt.timedelta(days=MAX_DAYS_AHEAD):
            raise ValueError(f"start_date must be between today and {MAX_DAYS_AHEAD} days ahead")
        return value


class DayWeatherOut(BaseModel):
    # "forecast": Open-Meteo forecast; "typical": average of the same dates in past years.
    source: Literal["forecast", "typical"]
    condition: Literal["clear", "partly_cloudy", "cloudy", "fog", "drizzle", "rain", "snow", "thunderstorm"]
    temp_max_c: float
    temp_min_c: float
    precipitation_chance: int | None
    is_rainy: bool


LegMode = Literal["WALK", "TRANSIT"]


class TransitRideOut(BaseModel):
    vehicle: str = Field(description='Google vehicle type, e.g. "SUBWAY", "BUS", "TRAM", "FERRY", "HEAVY_RAIL".')
    line: str = Field(description='The line\'s short name ("M2") when it has one, else its full name.')
    line_color: str | None = Field(default=None, examples=["#e30613"])
    line_text_color: str | None = None
    headsign: str | None = Field(default=None, description="The direction to take, usually the last stop.")
    from_stop: str
    to_stop: str
    stop_count: int
    minutes: int
    agency: str | None = Field(default=None, description="The operator, e.g. Metro Istanbul or RATP.")


class LegDetails(BaseModel):
    """How one leg of a transit plan is travelled: on foot, or by public transport."""

    mode: LegMode
    rides: list[TransitRideOut] = Field(default_factory=list, description="The rides in order; empty for a walk.")
    walk_minutes: int | None = Field(
        default=None, description="Time on foot, including walks to, from and between stops."
    )
    alternative_mode: LegMode | None = Field(
        default=None, description="The option not taken: walking instead of transit, or a faster transit option."
    )
    alternative_minutes: int | None = None


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
    # Transit plans only (and absent from plans saved before transit existed).
    leg_from_previous: LegDetails | None = None
    entry_price: Decimal | None = Field(examples=["17.00"])
    rating: float | None
    hours: str | None = Field(default=None, description='Opening hours that day, e.g. "09:00–18:00".')
    # A sentence or two from Wikipedia (CC BY-SA). Absent from plans saved before descriptions.
    wikidata_id: str | None = Field(
        default=None, description="The place's Wikidata item; links to its Wikipedia article in any language."
    )
    description_tr: str | None = None
    description_en: str | None = None


class DayPlan(BaseModel):
    day_number: int = Field(ge=1, le=MAX_TRIP_DAYS)
    stops: list[PlannedStop] = Field(max_length=MAX_STOPS_PER_DAY)
    return_travel_minutes: int
    return_distance_km: float
    return_path: str | None
    return_leg: LegDetails | None = None
    total_travel_minutes: int
    total_visit_minutes: int
    # "google": times from the Routes API; "estimate": straight-line fallback when Google is unavailable.
    routing_source: Literal["google", "estimate"]
    date: dt.date | None = None
    weather: DayWeatherOut | None = None
    # True when outdoor stops were moved away from this day because rain is expected.
    rain_adjusted: bool = False
    # Transit plans routed by Google: False when Google has no public transport data here, so
    # every leg is walked. None otherwise.
    transit_available: bool | None = None
    dropped_stops: list[str] = Field(
        default_factory=list, description="Stops left out because the day ran well over 8 hours."
    )


class RoutePlanResponse(BaseModel):
    city_id: str
    currency_code: str
    accommodation: Coordinates
    budget: Decimal | None
    travel_mode: TravelMode
    duration_days: int = Field(ge=1, le=MAX_TRIP_DAYS)
    start_date: dt.date | None = None
    total_entry_cost: Decimal = Field(examples=["34.00"])
    unpriced_stop_count: int = Field(description="Stops whose entry price is unknown (not counted in the cost).")
    price_basis: Literal["adult", "tr_citizen"] | None = Field(
        default=None,
        description='Which ticket the entry prices are: "adult" (standard adult ticket, the non-EU price where '
        'that differs) or "tr_citizen" (the price for Turkish citizens; foreign visitors pay more).',
    )
    prices_checked_on: dt.date | None = Field(default=None, description="When the entry prices were last checked.")
    days: list[DayPlan] = Field(max_length=MAX_TRIP_DAYS)


class RemoveStopRequest(BaseModel):
    plan: RoutePlanResponse = Field(description="The current plan, as returned by POST /routes/plan.")
    poi_id: str = Field(description="The stop to drop; its day is re-ordered and re-routed.")

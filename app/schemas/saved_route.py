from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.route import RoutePlanResponse
from app.services.routes_client import TravelMode


class SaveRouteRequest(BaseModel):
    name: str | None = Field(default=None, max_length=100, description="Defaults to e.g. 'Paris · 2 days'.")
    plan: RoutePlanResponse = Field(description="A plan as returned by POST /routes/plan.")


class SavedRouteSummary(BaseModel):
    id: str
    name: str
    city_id: str
    duration_days: int
    travel_mode: TravelMode
    stop_count: int
    created_at: datetime


class SavedRouteOut(SavedRouteSummary):
    plan: RoutePlanResponse

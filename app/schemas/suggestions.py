import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.route import MAX_STOPS_PER_DAY


class StopPoint(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class FoodRequest(BaseModel):
    stops: list[StopPoint] = Field(
        min_length=1, max_length=MAX_STOPS_PER_DAY, description="The day's stops in visiting order."
    )
    date: dt.date | None = Field(default=None, description="The day: places closed at meal times are left out.")
    lang: Literal["tr", "en"] = "en"


class FoodPlaceOut(BaseModel):
    place_id: str
    name: str
    cuisine: str | None = Field(description='In the requested language, e.g. "Turkish restaurant".')
    lat: float
    lng: float
    rating: float
    rating_count: int
    price_level: int | None = Field(description="0 (free) to 4 (very expensive); None if unknown.")
    hours: str | None = Field(description='Opening hours that day, e.g. "11:00–23:00"; None without a date.')
    distance_m: int = Field(description="Straight-line distance from the stop it is listed under.")
    maps_url: str | None


class FoodGroupOut(BaseModel):
    near: str = Field(description="The stop these places are close to.")
    places: list[FoodPlaceOut]

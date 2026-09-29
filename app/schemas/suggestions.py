import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.route import MAX_STOPS_PER_DAY, Coordinates


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


class NightlifeRequest(BaseModel):
    accommodation: Coordinates
    stops: list[StopPoint] = Field(default_factory=list, max_length=MAX_STOPS_PER_DAY)
    date: dt.date | None = Field(default=None, description="The day: places closed that evening are left out.")
    lang: Literal["tr", "en"] = "en"


class SuggestionOut(BaseModel):
    place_id: str
    name: str
    category: str | None = Field(description='In the requested language, e.g. "Turkish restaurant", "Cocktail bar".')
    lat: float
    lng: float
    rating: float
    rating_count: int
    price_level: int | None = Field(description="0 (free) to 4 (very expensive); None if unknown.")
    hours: str | None = Field(description='Opening hours that day, e.g. "18:00–02:00"; None without a date.')
    distance_m: int = Field(description="Straight-line distance from the place it is listed under.")
    maps_url: str | None


class SuggestionGroupOut(BaseModel):
    near: str | None = Field(description="The stop these places are close to; null for the accommodation.")
    places: list[SuggestionOut]

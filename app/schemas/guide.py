from typing import Literal

from pydantic import BaseModel, Field

from app.services.travel_guide import Continent


class GuideCityOut(BaseModel):
    id: str = Field(examples=["amsterdam"])
    country_code: str = Field(examples=["NL"], description="ISO 3166-1 alpha-2.")
    continent: Continent
    months: list[str] = Field(description="What the city is like each month, January first (12 texts).")
    note: str | None = Field(default=None, description="About the whole year, shown above the months.")


class BestPickOut(BaseModel):
    city_id: str
    text: str = Field(description="Why this city is among the month's best.")


class BestMonthOut(BaseModel):
    month: int = Field(ge=1, le=12)
    picks: list[BestPickOut]


class GuideOut(BaseModel):
    lang: Literal["tr", "en"]
    continents: list[Continent] = Field(description="In the order to show them.")
    cities: list[GuideCityOut]
    best: list[BestMonthOut] = Field(description="The five best cities for each month, January first.")

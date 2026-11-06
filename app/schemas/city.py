from pydantic import BaseModel

from app.services.travel_guide import Continent


class CityOut(BaseModel):
    id: str
    name: str  # English
    name_tr: str | None
    country_code: str | None
    continent: Continent | None
    currency_code: str
    poi_count: int
    # Average position of the city's POIs: where the map centres when the city is picked.
    center_lat: float | None
    center_lng: float | None


class SightOut(BaseModel):
    """One of a city's sights, shown on the map before a trip is planned."""

    poi_id: str
    name: str  # English
    name_tr: str | None
    category: str
    lat: float
    lng: float

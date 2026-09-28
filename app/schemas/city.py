from pydantic import BaseModel


class CityOut(BaseModel):
    id: str
    name: str
    currency_code: str
    poi_count: int
    # Average position of the city's POIs: where the map centres when the city is picked.
    center_lat: float | None
    center_lng: float | None

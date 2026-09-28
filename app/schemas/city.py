from pydantic import BaseModel


class CityOut(BaseModel):
    id: str
    name: str
    currency_code: str
    poi_count: int

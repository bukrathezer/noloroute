from pydantic import BaseModel


class PlaceSuggestionOut(BaseModel):
    place_id: str
    main_text: str
    secondary_text: str


class PlaceLocationOut(BaseModel):
    place_id: str
    lat: float
    lng: float
    address: str

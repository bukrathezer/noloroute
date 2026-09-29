"""Suggestions along a planned day that are not part of its route (see app/services/food.py)."""

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.v1.routes_places import Client
from app.core.rate_limit import RateLimiter, limit_by_ip
from app.schemas.suggestions import FoodGroupOut, FoodPlaceOut, FoodRequest
from app.services.food import Stop, food_suggestions
from app.services.geo import LatLng
from app.services.place_search import PlaceSearchError

router = APIRouter(prefix="/suggestions", tags=["suggestions"])

# Each lookup is two paid Nearby Search requests.
FOOD_LOOKUPS_PER_IP = RateLimiter(limit=30, window_seconds=60 * 60)


@router.post("/food", response_model=list[FoodGroupOut], dependencies=[Depends(limit_by_ip(FOOD_LOOKUPS_PER_IP))])
async def food(req: FoodRequest, client: Client) -> list[FoodGroupOut]:
    """Popular, well-rated places to eat a short walk from a day's stops, grouped by stop."""
    stops = [Stop(s.name, LatLng(s.lat, s.lng)) for s in req.stops]
    try:
        groups = await food_suggestions(client, stops, req.date, req.lang)
    except PlaceSearchError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Food search failed") from exc
    return [
        FoodGroupOut(
            near=group.near,
            places=[
                FoodPlaceOut(
                    place_id=p.place_id,
                    name=p.name,
                    cuisine=p.cuisine,
                    lat=p.location.lat,
                    lng=p.location.lng,
                    rating=p.rating,
                    rating_count=p.rating_count,
                    price_level=p.price_level,
                    hours=p.hours,
                    distance_m=p.distance_m,
                    maps_url=p.maps_url,
                )
                for p in group.places
            ],
        )
        for group in groups
    ]

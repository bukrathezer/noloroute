"""Suggestions around a planned day that are not part of its route (see app/services/suggestions.py)."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.v1.routes_places import Client
from app.core.rate_limit import RateLimiter, limit_by_ip
from app.schemas.suggestions import FoodRequest, NightlifeRequest, StopPoint, SuggestionGroupOut, SuggestionOut
from app.services.geo import LatLng
from app.services.place_search import PlaceSearchClient, PlaceSearchError
from app.services.suggestions import (
    FOOD,
    NIGHTLIFE,
    Anchor,
    Group,
    Kind,
    food_anchors,
    nightlife_anchors,
    suggestions,
)

router = APIRouter(prefix="/suggestions", tags=["suggestions"])

# Each lookup is up to two paid Nearby Search requests; food and nightlife share the limit.
SUGGESTION_LOOKUPS_PER_IP = RateLimiter(limit=30, window_seconds=60 * 60)
Limited = Depends(limit_by_ip(SUGGESTION_LOOKUPS_PER_IP))


@router.post("/food", response_model=list[SuggestionGroupOut], dependencies=[Limited])
async def food(req: FoodRequest, client: Client) -> list[SuggestionGroupOut]:
    """Popular, well-rated places to eat a short walk from a day's stops, grouped by stop."""
    return await _lookup(client, food_anchors(_anchors(req.stops)), FOOD, req.date, req.lang)


@router.post("/nightlife", response_model=list[SuggestionGroupOut], dependencies=[Limited])
async def nightlife(req: NightlifeRequest, client: Client) -> list[SuggestionGroupOut]:
    """Bars, clubs and live music open that evening near the accommodation (and the day's last
    stop, if it is far from it)."""
    hotel = LatLng(req.accommodation.lat, req.accommodation.lng)
    return await _lookup(client, nightlife_anchors(hotel, _anchors(req.stops)), NIGHTLIFE, req.date, req.lang)


def _anchors(stops: list[StopPoint]) -> list[Anchor]:
    return [Anchor(s.name, LatLng(s.lat, s.lng)) for s in stops]


async def _lookup(
    client: PlaceSearchClient, anchors: list[Anchor], kind: Kind, day: date | None, lang: str
) -> list[SuggestionGroupOut]:
    try:
        groups = await suggestions(client, anchors, kind, day, lang)
    except PlaceSearchError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Suggestion search failed") from exc
    return [_group_out(g) for g in groups]


def _group_out(group: Group) -> SuggestionGroupOut:
    return SuggestionGroupOut(
        near=group.near,
        places=[
            SuggestionOut(
                place_id=p.place_id,
                name=p.name,
                category=p.category,
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

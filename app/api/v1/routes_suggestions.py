"""Suggestions around a planned day that are not part of its route (see app/services/suggestions.py)."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.v1.routes_places import Client
from app.core.rate_limit import RateLimiter, limit_by_ip
from app.schemas.suggestions import (
    EventOut,
    EventsRequest,
    FoodRequest,
    NightlifeRequest,
    StopPoint,
    SuggestionGroupOut,
    SuggestionOut,
)
from app.services.events import EventsClient, EventsError
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

# Food and nightlife lookups are up to two paid Nearby Search requests each; events are free but
# Ticketmaster allows 5,000 a day. One limit covers all three.
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


def get_events_client(request: Request) -> EventsClient:
    client = request.app.state.events_client
    if client is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Event search is not configured")
    return client


@router.post("/events", response_model=list[EventOut], dependencies=[Limited])
async def events(req: EventsRequest, client: Annotated[EventsClient, Depends(get_events_client)]) -> list[EventOut]:
    """Concerts, sports, theatre and more starting on a trip day near the accommodation (Ticketmaster)."""
    try:
        found = await client.events_on(LatLng(req.accommodation.lat, req.accommodation.lng), req.date)
    except EventsError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Event search failed") from exc
    return [EventOut(**vars(e)) for e in found]


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

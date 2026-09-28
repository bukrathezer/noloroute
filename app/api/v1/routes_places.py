"""Search for an accommodation (hotel, address, landmark) by name, proxied to Google Places.

Proxying keeps the API key on the server and lets us rate-limit what each visitor can spend.
"""

import re
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status

from app.core.rate_limit import RateLimiter, limit_by_ip
from app.schemas.place import PlaceLocationOut, PlaceSuggestionOut
from app.services.geo import LatLng
from app.services.place_search import PlaceSearchClient, PlaceSearchError

router = APIRouter(prefix="/places", tags=["places"])

PLACE_SEARCHES_PER_IP = RateLimiter(limit=60, window_seconds=60)
_PLACE_ID = re.compile(r"^[A-Za-z0-9_-]{10,300}$")

SessionToken = Annotated[str, Query(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9-]+$")]
Language = Annotated[Literal["tr", "en"], Query()]


def get_place_search_client(request: Request) -> PlaceSearchClient:
    client = request.app.state.place_search_client
    if client is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Place search is not configured")
    return client


Client = Annotated[PlaceSearchClient, Depends(get_place_search_client)]


@router.get(
    "/autocomplete",
    response_model=list[PlaceSuggestionOut],
    dependencies=[Depends(limit_by_ip(PLACE_SEARCHES_PER_IP))],
)
async def autocomplete(
    client: Client,
    session_token: SessionToken,
    q: Annotated[str, Query(min_length=2, max_length=100)],
    lat: Annotated[float, Query(ge=-90, le=90)],
    lng: Annotated[float, Query(ge=-180, le=180)],
    lang: Language = "en",
) -> list[PlaceSuggestionOut]:
    """Suggestions for `q`, biased towards (lat, lng): usually the chosen city's centre."""
    try:
        suggestions = await client.autocomplete(q.strip(), LatLng(lat, lng), session_token, lang)
    except PlaceSearchError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Place search failed") from exc
    return [PlaceSuggestionOut(**vars(s)) for s in suggestions]


@router.get(
    "/{place_id}",
    response_model=PlaceLocationOut,
    dependencies=[Depends(limit_by_ip(PLACE_SEARCHES_PER_IP))],
)
async def place_location(
    client: Client,
    session_token: SessionToken,
    place_id: Annotated[str, Path()],
    lang: Language = "en",
) -> PlaceLocationOut:
    """Coordinates and address of a suggestion the user picked (ends the billing session)."""
    if not _PLACE_ID.match(place_id):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid place id")
    try:
        place = await client.location(place_id, session_token, lang)
    except PlaceSearchError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Place lookup failed") from exc
    return PlaceLocationOut(
        place_id=place.place_id, lat=place.location.lat, lng=place.location.lng, address=place.address
    )

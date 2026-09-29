"""Async Google Places (New) client for requests made while planning: Autocomplete + Place
Details to find an accommodation by name, and Nearby Search for suggestions along a route.

All keystrokes of one accommodation search and the final details lookup share a session token,
so Google bills them as a single session instead of per request.
"""

from dataclasses import dataclass
from typing import Any

import httpx

from app.services.geo import LatLng

BASE_URL = "https://places.googleapis.com/v1"
AUTOCOMPLETE_FIELDS = "suggestions.placePrediction.placeId,suggestions.placePrediction.structuredFormat"
DETAILS_FIELDS = "location,formattedAddress"  # Essentials SKU: the cheapest details tier
BIAS_RADIUS_M = 30_000.0


class PlaceSearchError(Exception):
    pass


@dataclass(frozen=True)
class Suggestion:
    place_id: str
    main_text: str
    secondary_text: str


@dataclass(frozen=True)
class PlaceLocation:
    place_id: str
    location: LatLng
    address: str


class PlaceSearchClient:
    def __init__(self, api_key: str, timeout: float = 8.0) -> None:
        self._http = httpx.AsyncClient(base_url=BASE_URL, timeout=timeout, headers={"X-Goog-Api-Key": api_key})

    async def aclose(self) -> None:
        await self._http.aclose()

    async def autocomplete(self, text: str, near: LatLng, session_token: str, language: str) -> list[Suggestion]:
        body = {
            "input": text,
            "sessionToken": session_token,
            "languageCode": language,
            # Prefer results around the chosen city without excluding everything else.
            "locationBias": {
                "circle": {"center": {"latitude": near.lat, "longitude": near.lng}, "radius": BIAS_RADIUS_M}
            },
        }
        data = await self._request("POST", "/places:autocomplete", AUTOCOMPLETE_FIELDS, json=body)
        suggestions = []
        for item in data.get("suggestions", []):
            prediction = item.get("placePrediction")
            if not prediction:
                continue
            fmt = prediction.get("structuredFormat", {})
            suggestions.append(
                Suggestion(
                    place_id=prediction["placeId"],
                    main_text=fmt.get("mainText", {}).get("text", ""),
                    secondary_text=fmt.get("secondaryText", {}).get("text", ""),
                )
            )
        return suggestions

    async def location(self, place_id: str, session_token: str, language: str) -> PlaceLocation:
        data = await self._request(
            "GET",
            f"/places/{place_id}",
            DETAILS_FIELDS,
            params={"sessionToken": session_token, "languageCode": language},
        )
        loc = data.get("location")
        if not loc:
            raise PlaceSearchError("place has no location")
        return PlaceLocation(
            place_id=place_id,
            location=LatLng(loc["latitude"], loc["longitude"]),
            address=data.get("formattedAddress", ""),
        )

    async def search_nearby(
        self,
        center: LatLng,
        radius_m: float,
        included_types: list[str],
        field_mask: str,
        language: str,
        excluded_primary_types: list[str] | None = None,
        primary_types_only: bool = False,
    ) -> list[dict[str, Any]]:
        """Up to 20 places of the given types within the circle, most popular first.

        With `primary_types_only`, a place's main type must be one of them (a restaurant that
        also has a bar doesn't count as a bar).
        """
        body: dict[str, Any] = {
            "includedPrimaryTypes" if primary_types_only else "includedTypes": included_types,
            "maxResultCount": 20,
            "rankPreference": "POPULARITY",
            "languageCode": language,
            "locationRestriction": {
                "circle": {"center": {"latitude": center.lat, "longitude": center.lng}, "radius": radius_m}
            },
        }
        if excluded_primary_types:
            body["excludedPrimaryTypes"] = excluded_primary_types
        data = await self._request("POST", "/places:searchNearby", field_mask, json=body)
        return data.get("places", [])

    async def _request(self, method: str, path: str, field_mask: str, **kwargs: Any) -> dict[str, Any]:
        try:
            resp = await self._http.request(method, path, headers={"X-Goog-FieldMask": field_mask}, **kwargs)
        except httpx.HTTPError as exc:
            raise PlaceSearchError(f"request failed: {exc}") from exc
        if resp.is_error:
            raise PlaceSearchError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        return resp.json()

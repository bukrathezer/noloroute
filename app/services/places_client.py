"""Thin client for the Google Places API (New): Nearby Search and Text Search."""

import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Self

import httpx

from app.services.geo import LatLng

BASE_URL = "https://places.googleapis.com/v1"

# Only request the fields we store: the field mask also decides which billing SKU applies.
PLACE_FIELDS = [
    "id",
    "displayName",
    "location",
    "types",
    "primaryType",
    "rating",
    "userRatingCount",
    "businessStatus",
    "regularOpeningHours",
]
PLACES_FIELD_MASK = ",".join(f"places.{field}" for field in PLACE_FIELDS)

MAX_NEARBY_RESULTS = 20  # API maximum per Nearby Search request; there is no pagination
TEXT_PAGE_SIZE = 20
TEXT_MAX_PAGES = 3  # Text Search returns at most 60 results (3 pages of 20) per query
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3


class PlacesAPIError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"Places API error {status_code}: {message}")
        self.status_code = status_code


@dataclass(frozen=True)
class BoundingBox:
    south: float
    west: float
    north: float
    east: float


class PlacesClient:
    def __init__(self, api_key: str, language: str = "en", timeout: float = 15.0) -> None:
        self._language = language
        self._http = httpx.Client(base_url=BASE_URL, timeout=timeout, headers={"X-Goog-Api-Key": api_key})

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def search_nearby(
        self, center: LatLng, radius_m: float, included_types: list[str]
    ) -> list[dict[str, Any]]:
        """Return up to 20 places of the given types within the circle, most popular first."""
        body = {
            "includedTypes": included_types,
            "maxResultCount": MAX_NEARBY_RESULTS,
            "rankPreference": "POPULARITY",
            "languageCode": self._language,
            "locationRestriction": {
                "circle": {"center": {"latitude": center.lat, "longitude": center.lng}, "radius": radius_m}
            },
        }
        return self._post("/places:searchNearby", body, PLACES_FIELD_MASK).get("places", [])

    def search_text(
        self, query: str, bounds: BoundingBox, included_type: str | None = None
    ) -> Iterator[dict[str, Any]]:
        """Yield places for a text query (ranked by relevance) inside `bounds`, following pagination."""
        body: dict[str, Any] = {
            "textQuery": query,
            "languageCode": self._language,
            "pageSize": TEXT_PAGE_SIZE,
            "locationRestriction": {
                "rectangle": {
                    "low": {"latitude": bounds.south, "longitude": bounds.west},
                    "high": {"latitude": bounds.north, "longitude": bounds.east},
                }
            },
        }
        if included_type:
            body["includedType"] = included_type
            body["strictTypeFiltering"] = True

        for _ in range(TEXT_MAX_PAGES):
            data = self._post("/places:searchText", body, f"{PLACES_FIELD_MASK},nextPageToken")
            yield from data.get("places", [])
            token = data.get("nextPageToken")
            if not token:
                return
            body = {**body, "pageToken": token}

    def _post(self, path: str, body: dict[str, Any], field_mask: str) -> dict[str, Any]:
        for attempt in range(MAX_ATTEMPTS):
            resp = self._http.post(path, json=body, headers={"X-Goog-FieldMask": field_mask})
            if resp.status_code in RETRYABLE_STATUS and attempt < MAX_ATTEMPTS - 1:
                time.sleep(2**attempt)  # 1s, 2s backoff for rate limits / transient errors
                continue
            if resp.is_error:
                raise PlacesAPIError(resp.status_code, _error_message(resp))
            return resp.json()
        raise AssertionError("unreachable")


def _error_message(resp: httpx.Response) -> str:
    try:
        return resp.json()["error"]["message"]
    except (ValueError, KeyError, TypeError):
        return resp.text

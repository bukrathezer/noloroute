"""Async client for the Google Routes API: orders a day's stops as a loop from the hotel."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import httpx

from app.services.geo import LatLng

COMPUTE_ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
FIELD_MASK = "routes.optimizedIntermediateWaypointIndex,routes.legs.duration,routes.legs.distanceMeters"
MAX_INTERMEDIATES = 25  # API limit when optimizeWaypointOrder is on


class TravelMode(StrEnum):
    # TRANSIT is not offered: the Routes API can't optimize waypoint order for transit.
    DRIVE = "DRIVE"
    WALK = "WALK"


class RoutesAPIError(Exception):
    pass


@dataclass(frozen=True)
class Leg:
    seconds: int
    meters: int


@dataclass(frozen=True)
class LoopRoute:
    """A hotel -> stops -> hotel loop.

    `order` lists indexes into the input stops in visiting order; `legs` has len(stops) + 1
    entries: hotel -> first stop, ..., last stop -> hotel.
    """

    order: list[int]
    legs: list[Leg]


class RoutesClient:
    def __init__(self, api_key: str, timeout: float = 10.0) -> None:
        self._http = httpx.AsyncClient(
            timeout=timeout, headers={"X-Goog-Api-Key": api_key, "X-Goog-FieldMask": FIELD_MASK}
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def optimize_loop(self, origin: LatLng, stops: list[LatLng], mode: TravelMode) -> LoopRoute:
        if not 1 <= len(stops) <= MAX_INTERMEDIATES:
            raise ValueError(f"expected 1..{MAX_INTERMEDIATES} stops, got {len(stops)}")

        body: dict[str, Any] = {
            "origin": _waypoint(origin),
            "destination": _waypoint(origin),
            "intermediates": [_waypoint(stop) for stop in stops],
            "travelMode": mode.value,
            "optimizeWaypointOrder": True,
        }
        if mode is TravelMode.DRIVE:
            body["routingPreference"] = "TRAFFIC_UNAWARE"  # traffic-aware routing can't reorder waypoints

        try:
            resp = await self._http.post(COMPUTE_ROUTES_URL, json=body)
        except httpx.HTTPError as exc:
            raise RoutesAPIError(f"request failed: {exc}") from exc
        if resp.is_error:
            raise RoutesAPIError(f"HTTP {resp.status_code}: {resp.text[:300]}")

        routes = resp.json().get("routes")
        if not routes:
            raise RoutesAPIError("no route found")  # e.g. WALK across water with no pedestrian path
        route = routes[0]
        # Omitted when there is nothing to reorder (a single stop).
        order = route.get("optimizedIntermediateWaypointIndex") or list(range(len(stops)))
        legs = [
            Leg(seconds=_parse_duration(leg.get("duration", "0s")), meters=leg.get("distanceMeters", 0))
            for leg in route["legs"]
        ]
        return LoopRoute(order=order, legs=legs)


def _waypoint(point: LatLng) -> dict[str, Any]:
    return {"location": {"latLng": {"latitude": point.lat, "longitude": point.lng}}}


def _parse_duration(value: str) -> int:
    # The API encodes durations as strings like "754s".
    return round(float(value.removesuffix("s")))

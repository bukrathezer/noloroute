"""Async client for the Google Routes API.

- optimize_loop:  orders a day's stops as a loop from the hotel (walking and driving).
- compute_matrix: travel times between every pair of points (Route Matrix), for transit planning.
- route_leg:      one A -> B route with its street path and, for transit, the lines to take.
"""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import httpx

from app.services.geo import LatLng

COMPUTE_ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
ROUTE_MATRIX_URL = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"
LOOP_FIELD_MASK = ",".join(
    [
        "routes.optimizedIntermediateWaypointIndex",
        "routes.legs.duration",
        "routes.legs.distanceMeters",
        "routes.legs.polyline.encodedPolyline",  # street-level path, drawn on the map
    ]
)
LEG_FIELD_MASK = ",".join(
    [
        "routes.legs.duration",
        "routes.legs.distanceMeters",
        "routes.legs.polyline.encodedPolyline",
        "routes.legs.steps.travelMode",
        "routes.legs.steps.staticDuration",
        "routes.legs.steps.transitDetails",  # line, stops and vehicle of each ride
    ]
)
# "status" must be asked for, or every element looks successful.
MATRIX_FIELD_MASK = "originIndex,destinationIndex,status,condition,duration,distanceMeters"
MAX_INTERMEDIATES = 25  # API limit when optimizeWaypointOrder is on
MAX_MATRIX_ELEMENTS = 625  # origins x destinations per Route Matrix request
MAX_TRANSIT_MATRIX_ELEMENTS = 100  # lower limit for TRANSIT


class TravelMode(StrEnum):
    DRIVE = "DRIVE"
    WALK = "WALK"
    # As a plan's mode: walking plus public transport, each leg taking whichever is better
    # (see app/services/transit_planner.py). As a Google travel mode: public transport.
    TRANSIT = "TRANSIT"


class RoutesAPIError(Exception):
    pass


@dataclass(frozen=True)
class TransitRide:
    """One ride on a public transport line."""

    vehicle: str  # Google vehicle type: BUS, SUBWAY, TRAM, FERRY, HEAVY_RAIL, ...
    line: str  # the short name ("M2") when there is one, else the full name
    line_color: str | None
    line_text_color: str | None
    headsign: str | None  # the direction, e.g. the last stop
    from_stop: str
    to_stop: str
    stop_count: int
    seconds: int
    agency: str | None


@dataclass(frozen=True)
class Leg:
    seconds: int
    meters: int
    polyline: str | None = None  # Google encoded polyline; None for straight-line estimates
    # Only set in transit plans, where each leg is either walked or ridden:
    mode: TravelMode | None = None
    rides: tuple[TransitRide, ...] = ()
    walk_seconds: int | None = None  # time on foot within the leg
    alternative: tuple[TravelMode, int] | None = None  # the option not taken: (mode, seconds)


@dataclass(frozen=True)
class LoopRoute:
    """A hotel -> stops -> hotel loop.

    `order` lists indexes into the input stops in visiting order; `legs` has len(stops) + 1
    entries: hotel -> first stop, ..., last stop -> hotel.
    """

    order: list[int]
    legs: list[Leg]


@dataclass(frozen=True)
class MatrixCell:
    seconds: int
    meters: int


# matrix[i][j]: from point i to point j, or None where there is no route.
Matrix = list[list[MatrixCell | None]]


class RoutesClient:
    def __init__(self, api_key: str, timeout: float = 10.0, transport: httpx.AsyncBaseTransport | None = None) -> None:
        # `transport` lets tests answer requests without the network.
        self._http = httpx.AsyncClient(timeout=timeout, headers={"X-Goog-Api-Key": api_key}, transport=transport)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def optimize_loop(self, origin: LatLng, stops: list[LatLng], mode: TravelMode) -> LoopRoute:
        if mode is TravelMode.TRANSIT:
            raise ValueError("the Routes API can't optimize the order of transit waypoints")
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

        route = await self._first_route(body, LOOP_FIELD_MASK)
        # Omitted when there is nothing to reorder (a single stop).
        order = route.get("optimizedIntermediateWaypointIndex") or list(range(len(stops)))
        legs = [
            Leg(
                seconds=_parse_duration(leg.get("duration", "0s")),
                meters=leg.get("distanceMeters", 0),
                polyline=leg.get("polyline", {}).get("encodedPolyline"),
            )
            for leg in route["legs"]
        ]
        return LoopRoute(order=order, legs=legs)

    async def compute_matrix(self, points: list[LatLng], mode: TravelMode, departure: datetime | None = None) -> Matrix:
        """Travel from every point to every other point. `departure` is used for transit only.

        Google caps the elements (origins x destinations) per request, so larger matrices are
        requested in blocks of rows, side by side.
        """
        limit = MAX_TRANSIT_MATRIX_ELEMENTS if mode is TravelMode.TRANSIT else MAX_MATRIX_ELEMENTS
        n = len(points)
        if not 1 <= n <= limit:
            raise ValueError(f"expected 1..{limit} points, got {n}")
        rows_per_request = limit // n
        blocks = [list(range(start, min(start + rows_per_request, n))) for start in range(0, n, rows_per_request)]
        results = await asyncio.gather(*(self._matrix_rows(points, rows, mode, departure) for rows in blocks))
        return [row for block in results for row in block]

    async def _matrix_rows(
        self, points: list[LatLng], rows: list[int], mode: TravelMode, departure: datetime | None
    ) -> Matrix:
        body: dict[str, Any] = {
            "origins": [{"waypoint": _waypoint(points[i])} for i in rows],
            "destinations": [{"waypoint": _waypoint(p)} for p in points],
            "travelMode": mode.value,
        }
        if mode is TravelMode.TRANSIT and departure is not None:
            body["departureTime"] = _timestamp(departure)
        elements = await self._post(ROUTE_MATRIX_URL, body, MATRIX_FIELD_MASK)
        if not isinstance(elements, list):
            raise RoutesAPIError(f"unexpected matrix response: {str(elements)[:300]}")
        return parse_matrix(elements, len(rows), len(points))

    async def route_leg(
        self, origin: LatLng, destination: LatLng, mode: TravelMode, departure: datetime | None = None
    ) -> Leg:
        """One A -> B route. For transit, `departure` picks the timetable and the leg lists its rides."""
        body: dict[str, Any] = {
            "origin": _waypoint(origin),
            "destination": _waypoint(destination),
            "travelMode": mode.value,
        }
        if mode is TravelMode.TRANSIT and departure is not None:
            body["departureTime"] = _timestamp(departure)
        route = await self._first_route(body, LEG_FIELD_MASK)
        return parse_leg(route["legs"][0])

    async def _first_route(self, body: dict[str, Any], field_mask: str) -> dict[str, Any]:
        routes = (await self._post(COMPUTE_ROUTES_URL, body, field_mask)).get("routes")
        if not routes:
            raise RoutesAPIError("no route found")  # e.g. WALK across water with no pedestrian path
        return routes[0]

    async def _post(self, url: str, body: dict[str, Any], field_mask: str) -> Any:
        try:
            resp = await self._http.post(url, json=body, headers={"X-Goog-FieldMask": field_mask})
        except httpx.HTTPError as exc:
            raise RoutesAPIError(f"request failed: {exc}") from exc
        if resp.is_error:
            raise RoutesAPIError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        return resp.json()


def parse_matrix(elements: list[dict[str, Any]], n_rows: int, n_cols: int) -> Matrix:
    matrix: Matrix = [[None] * n_cols for _ in range(n_rows)]
    for element in elements:
        if element.get("condition") != "ROUTE_EXISTS" or element.get("status", {}).get("code"):
            continue
        # Zero values are left out of the JSON, so a missing index means 0.
        i, j = element.get("originIndex", 0), element.get("destinationIndex", 0)
        matrix[i][j] = MatrixCell(
            seconds=_parse_duration(element.get("duration", "0s")), meters=element.get("distanceMeters", 0)
        )
    return matrix


def parse_leg(leg: dict[str, Any]) -> Leg:
    """A computeRoutes leg; its transit steps become rides, the rest counts as walking."""
    rides: list[TransitRide] = []
    walk_seconds = 0
    for step in leg.get("steps", []):
        seconds = _parse_duration(step.get("staticDuration", "0s"))
        details = step.get("transitDetails")
        if step.get("travelMode") == "TRANSIT" and details:
            rides.append(_parse_ride(details, seconds))
        else:
            walk_seconds += seconds
    return Leg(
        seconds=_parse_duration(leg.get("duration", "0s")),
        meters=leg.get("distanceMeters", 0),
        polyline=leg.get("polyline", {}).get("encodedPolyline"),
        mode=TravelMode.TRANSIT if rides else TravelMode.WALK,
        rides=tuple(rides),
        walk_seconds=walk_seconds,
    )


def _parse_ride(details: dict[str, Any], seconds: int) -> TransitRide:
    line = details.get("transitLine", {})
    stops = details.get("stopDetails", {})
    agencies = line.get("agencies") or [{}]
    return TransitRide(
        vehicle=line.get("vehicle", {}).get("type", "OTHER"),
        line=line.get("nameShort") or line.get("name") or "?",
        line_color=line.get("color"),
        line_text_color=line.get("textColor"),
        headsign=details.get("headsign"),
        from_stop=stops.get("departureStop", {}).get("name", ""),
        to_stop=stops.get("arrivalStop", {}).get("name", ""),
        stop_count=details.get("stopCount", 0),
        seconds=seconds,
        agency=agencies[0].get("name"),
    )


def _waypoint(point: LatLng) -> dict[str, Any]:
    return {"location": {"latLng": {"latitude": point.lat, "longitude": point.lng}}}


def _timestamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_duration(value: str) -> int:
    # The API encodes durations as strings like "754s".
    return round(float(value.removesuffix("s")))

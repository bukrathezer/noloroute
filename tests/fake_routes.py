"""A stand-in for the Google Routes client in transit tests: times follow straight-line distance."""

from datetime import datetime

from app.services.geo import LatLng, haversine_km
from app.services.routes_client import Leg, LoopRoute, MatrixCell, RoutesAPIError, TransitRide, TravelMode

WALK_KMH = 5.0
TRANSIT_KMH = 20.0
TRANSIT_WAIT_SECONDS = 6 * 60
TRANSIT_MIN_KM = 1.5  # by default, closer than this the fake has no transit route (as if there were no line)


class FakeTransitClient:
    def __init__(
        self,
        has_transit: bool = True,
        fail_matrix: bool = False,
        fail_legs: bool = False,
        transit_min_km: float = TRANSIT_MIN_KM,
    ) -> None:
        self.has_transit = has_transit
        self.transit_min_km = transit_min_km
        self.fail_matrix = fail_matrix
        self.fail_legs = fail_legs
        self.matrix_calls: list[tuple[TravelMode, int, datetime | None]] = []  # mode, points, departure
        self.leg_calls: list[tuple[TravelMode, datetime | None]] = []

    def seconds(self, a: LatLng, b: LatLng, mode: TravelMode) -> int | None:
        km = haversine_km(a, b)
        if mode is TravelMode.WALK:
            return round(km / WALK_KMH * 3600)
        if not self.has_transit or km < self.transit_min_km:
            return None
        return TRANSIT_WAIT_SECONDS + round(km / TRANSIT_KMH * 3600)

    async def compute_matrix(
        self, points: list[LatLng], mode: TravelMode, departure: datetime | None = None
    ) -> list[list[MatrixCell | None]]:
        self.matrix_calls.append((mode, len(points), departure))
        if self.fail_matrix:
            raise RoutesAPIError("matrix down")
        return [
            [
                MatrixCell(s, round(haversine_km(a, b) * 1000)) if (s := self.seconds(a, b, mode)) is not None else None
                for b in points
            ]
            for a in points
        ]

    async def route_leg(
        self, origin: LatLng, destination: LatLng, mode: TravelMode, departure: datetime | None = None
    ) -> Leg:
        self.leg_calls.append((mode, departure))
        if self.fail_legs:
            raise RoutesAPIError("leg down")
        seconds = self.seconds(origin, destination, mode)
        assert seconds is not None, "only legs with a route are asked for"
        meters = round(haversine_km(origin, destination) * 1000)
        if mode is TravelMode.WALK:
            return Leg(seconds, meters, "walk-path", TravelMode.WALK, walk_seconds=seconds)
        ride = TransitRide(
            vehicle="SUBWAY",
            line="M1",
            line_color="#ffcd00",
            line_text_color="#000000",
            headsign="La Défense",
            from_stop="Hôtel de Ville",
            to_stop="Concorde",
            stop_count=4,
            seconds=seconds - 2 * 60 - TRANSIT_WAIT_SECONDS,
            agency="RATP",
        )
        return Leg(seconds, meters, "transit-path", TravelMode.TRANSIT, (ride,), walk_seconds=2 * 60)

    async def optimize_loop(self, origin: LatLng, stops: list[LatLng], mode: TravelMode) -> LoopRoute:
        raise AssertionError("transit plans are ordered by our own solver")

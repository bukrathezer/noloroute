"""Small geometry helpers on lat/lng coordinates."""

import math
from dataclasses import dataclass

EARTH_RADIUS_KM = 6371.0
DETOUR_FACTOR = 1.3  # streets aren't straight lines: real routes are about this much longer


@dataclass(frozen=True)
class LatLng:
    lat: float
    lng: float


def haversine_km(a: LatLng, b: LatLng) -> float:
    """Great-circle (straight-line) distance between two points in km."""
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    dlat = lat2 - lat1
    dlng = math.radians(b.lng - a.lng)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def bearing_rad(origin: LatLng, point: LatLng) -> float:
    """Direction from origin to point as an angle in (-pi, pi]; fine for city-scale distances."""
    dx = (point.lng - origin.lng) * math.cos(math.radians(origin.lat))
    dy = point.lat - origin.lat
    return math.atan2(dy, dx)

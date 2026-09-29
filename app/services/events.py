"""Events on a trip day near the accommodation (concerts, sports, theatre, ...), from the
Ticketmaster Discovery API.

Google has no event data, so this is a second source. Like the other suggestions, events are
looked up only when the traveller asks and are not stored. Coverage varies a lot: on a Saturday
in October 2026 it listed 129 events around London, 26 around Istanbul (Biletix is part of
Ticketmaster), 13-14 in Amsterdam and Madrid, 1 in Rome and none in Paris.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx

from app.services.geo import LatLng, haversine_km

EVENTS_URL = "https://app.ticketmaster.com/discovery/v2/events.json"
SEARCH_RADIUS_KM = 15
MAX_EVENTS = 8
# Concerts, sports, theatre. Left out: "Miscellaneous", which is mostly timed entry tickets to
# attractions (a London Eye slot every half hour) that would crowd out the actual events.
SEGMENTS = "Music,Sports,Arts & Theatre"
_GEOHASH_ALPHABET = "0123456789bcdefghjkmnpqrstuvwxyz"


class EventsError(Exception):
    pass


@dataclass(frozen=True)
class Event:
    name: str
    segment: str | None  # Ticketmaster's main category: "Music", "Sports", "Arts & Theatre", ...
    genre: str | None  # "Rock", "Football", "Theatre"
    times: list[str]  # local start times that day, e.g. ["14:30", "19:30"]; empty if unknown
    venue: str | None
    distance_km: float | None  # from the accommodation
    url: str | None  # the event's Ticketmaster page, for details and tickets
    price_min: float | None
    price_max: float | None
    currency: str | None


class EventsClient:
    def __init__(self, api_key: str, timeout: float = 8.0, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._api_key = api_key
        self._http = httpx.AsyncClient(timeout=timeout, transport=transport)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def events_on(self, near: LatLng, day: date) -> list[Event]:
        """The most relevant events starting on `day` (local time) within SEARCH_RADIUS_KM of `near`,
        in order of time."""
        params = {
            "apikey": self._api_key,
            "geoPoint": geohash(near),
            "radius": str(SEARCH_RADIUS_KM),
            "unit": "km",
            "localStartDateTime": f"{day.isoformat()}T00:00:00,{day.isoformat()}T23:59:59",
            "classificationName": SEGMENTS,
            # Most relevant first: sorting by date would fill the page with the morning's events.
            "sort": "relevance,desc",
            "size": "50",
        }
        try:
            resp = await self._http.get(EVENTS_URL, params=params)
        except httpx.HTTPError as exc:
            raise EventsError(f"request failed: {exc}") from exc
        if resp.is_error:
            raise EventsError(f"HTTP {resp.status_code}")  # the URL holds the API key: don't log it
        return parse_events(resp.json(), near)


def parse_events(data: dict[str, Any], near: LatLng) -> list[Event]:
    """Ticketmaster events as a short list: cancelled ones left out, several showings of the same
    event at the same venue merged into one entry with all its times, the MAX_EVENTS most
    relevant kept (the API returns them in that order) and put in order of time."""
    shows: dict[tuple[str, str | None], list[dict[str, Any]]] = defaultdict(list)
    for event in data.get("_embedded", {}).get("events", []):
        if event.get("dates", {}).get("status", {}).get("code") in {"cancelled", "postponed"}:
            continue
        venue = (event.get("_embedded", {}).get("venues") or [{}])[0]
        shows[(event.get("name", ""), venue.get("name"))].append(event)

    events = []
    for (name, venue_name), group in shows.items():
        first = group[0]
        venue = (first.get("_embedded", {}).get("venues") or [{}])[0]
        location = venue.get("location") or {}
        distance = None
        if "latitude" in location and "longitude" in location:
            where = LatLng(float(location["latitude"]), float(location["longitude"]))
            distance = round(haversine_km(near, where), 1)
        prices = [p for e in group for p in e.get("priceRanges", [])]
        times = sorted({t[:5] for e in group if (t := e.get("dates", {}).get("start", {}).get("localTime"))})
        events.append(
            Event(
                name=name,
                segment=_classification(first, "segment"),
                genre=_classification(first, "genre"),
                times=times,
                venue=venue_name,
                distance_km=distance,
                url=first.get("url"),
                price_min=min((p["min"] for p in prices if "min" in p), default=None),
                price_max=max((p["max"] for p in prices if "max" in p), default=None),
                currency=next((p.get("currency") for p in prices), None),
            )
        )
    events = events[:MAX_EVENTS]
    # Timed events first by time, then those without a time.
    events.sort(key=lambda e: (not e.times, e.times[:1]))
    return events


def _classification(event: dict[str, Any], level: str) -> str | None:
    name = (event.get("classifications") or [{}])[0].get(level, {}).get("name")
    return name if name and name != "Undefined" else None


def geohash(point: LatLng, precision: int = 9) -> str:
    """The standard geohash of a point: alternate halving of the longitude and latitude ranges,
    five bits per base-32 character."""
    lat_range, lng_range = [-90.0, 90.0], [-180.0, 180.0]
    chars, bits, bit_count, even = [], 0, 0, True
    while len(chars) < precision:
        rng, value = (lng_range, point.lng) if even else (lat_range, point.lat)
        mid = (rng[0] + rng[1]) / 2
        if value >= mid:
            bits = bits * 2 + 1
            rng[0] = mid
        else:
            bits *= 2
            rng[1] = mid
        even = not even
        bit_count += 1
        if bit_count == 5:
            chars.append(_GEOHASH_ALPHABET[bits])
            bits, bit_count = 0, 0
    return "".join(chars)

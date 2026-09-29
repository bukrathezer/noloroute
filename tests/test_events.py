import asyncio
from collections.abc import Iterator
from datetime import date

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.v1.routes_suggestions import get_events_client
from app.main import app
from app.services.events import MAX_EVENTS, Event, EventsClient, EventsError, geohash, parse_events
from app.services.geo import LatLng

LONDON = LatLng(51.5074, -0.1278)
DAY = date(2026, 10, 12)


def event(name: str, time: str | None = "19:30:00", venue: str = "O2 Arena", **extra) -> dict:
    return {
        "name": name,
        "url": f"https://www.ticketmaster.co.uk/{name.lower().replace(' ', '-')}",
        "dates": {"start": {"localDate": DAY.isoformat(), **({"localTime": time} if time else {})}},
        "classifications": [{"segment": {"name": "Music"}, "genre": {"name": "Rock"}}],
        "_embedded": {"venues": [{"name": venue, "location": {"latitude": "51.5030", "longitude": "0.0032"}}]},
        **extra,
    }


def response(*events: dict) -> dict:
    return {"_embedded": {"events": list(events)}}


def test_geohash_matches_the_reference_encoding() -> None:
    assert geohash(LatLng(57.64911, 10.40744), 11) == "u4pruydqqvj"  # the example on Wikipedia
    assert geohash(LONDON).startswith("gcpvj")


def test_showings_of_the_same_event_are_merged() -> None:
    data = response(
        event("Hamilton", "19:30:00", venue="Victoria Palace"),
        event("Hamilton", "14:30:00", venue="Victoria Palace"),
        event("Rock Night", "20:00:00"),
    )
    events = parse_events(data, LONDON)
    assert [(e.name, e.times) for e in events] == [("Hamilton", ["14:30", "19:30"]), ("Rock Night", ["20:00"])]


def test_event_details_are_read() -> None:
    data = response(
        event(
            "Rock Night",
            priceRanges=[{"type": "standard", "currency": "GBP", "min": 45.0, "max": 120.0}],
            classifications=[{"segment": {"name": "Music"}, "genre": {"name": "Undefined"}}],
        )
    )
    [e] = parse_events(data, LONDON)
    assert (e.segment, e.genre, e.venue, e.price_min, e.price_max, e.currency) == (
        "Music",
        None,  # "Undefined" genres are left out
        "O2 Arena",
        45.0,
        120.0,
        "GBP",
    )
    assert e.distance_km == pytest.approx(9.1, abs=0.3)
    assert e.url and e.url.startswith("https://www.ticketmaster")


def test_cancelled_events_are_left_out_and_untimed_ones_go_last() -> None:
    data = response(
        event("No Time", None),
        event("Cancelled", dates={"start": {"localTime": "18:00:00"}, "status": {"code": "cancelled"}}),
        event("Evening", "21:00:00"),
        event("Afternoon", "15:00:00", venue="Wembley"),
    )
    assert [e.name for e in parse_events(data, LONDON)] == ["Afternoon", "Evening", "No Time"]


def test_the_most_relevant_are_kept_then_ordered_by_time() -> None:
    # The API lists events most relevant first; the last ones start earliest but don't make the cut.
    relevant = [event(f"Show {i}", f"{19 - i % 3}:00:00", venue=f"Venue {i}") for i in range(MAX_EVENTS)]
    also_ran = [event(f"Matinee {i}", "11:00:00", venue=f"Hall {i}") for i in range(2)]
    events = parse_events(response(*relevant, *also_ran), LONDON)
    assert {e.name for e in events} == {f"Show {i}" for i in range(MAX_EVENTS)}
    assert [e.times[0] for e in events] == sorted(e.times[0] for e in events)


def test_the_list_is_short() -> None:
    data = response(*[event(f"Show {i}", f"{10 + i}:00:00", venue=f"Venue {i}") for i in range(12)])
    assert len(parse_events(data, LONDON)) == MAX_EVENTS
    assert parse_events({}, LONDON) == []  # no events at all: no "_embedded"


def test_the_client_asks_for_that_day_around_the_point() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=response(event("Rock Night")))

    client = EventsClient("secret-key", transport=httpx.MockTransport(handler))
    [e] = asyncio.run(client.events_on(LONDON, DAY))
    params = seen[0].url.params
    assert params["geoPoint"] == geohash(LONDON) and params["unit"] == "km"
    assert params["localStartDateTime"] == "2026-10-12T00:00:00,2026-10-12T23:59:59"
    assert params["classificationName"] == "Music,Sports,Arts & Theatre" and params["sort"] == "relevance,desc"
    assert e.name == "Rock Night"


def test_client_errors_do_not_leak_the_key() -> None:
    client = EventsClient("secret-key", transport=httpx.MockTransport(lambda r: httpx.Response(401, text="bad key")))
    with pytest.raises(EventsError) as info:
        asyncio.run(client.events_on(LONDON, DAY))
    assert "secret-key" not in str(info.value)


# --- the API ------------------------------------------------------------------------------------------


class FakeEvents:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    async def events_on(self, near: LatLng, day: date) -> list[Event]:
        if self.fail:
            raise EventsError("down")
        return [Event("Rock Night", "Music", "Rock", ["20:00"], "O2 Arena", 9.1, "https://tm/rock", 45.0, 120.0, "GBP")]


@pytest.fixture
def api() -> Iterator[tuple[TestClient, FakeEvents]]:
    fake = FakeEvents()
    app.dependency_overrides[get_events_client] = lambda: fake
    try:
        with TestClient(app) as test_client:
            yield test_client, fake
    finally:
        app.dependency_overrides.clear()


BODY = {"accommodation": {"lat": LONDON.lat, "lng": LONDON.lng}, "date": DAY.isoformat()}


def test_events_endpoint(api) -> None:
    client, fake = api
    resp = client.post("/api/v1/suggestions/events", json=BODY)
    assert resp.status_code == 200, resp.text
    [found] = resp.json()
    assert found == {
        "name": "Rock Night",
        "segment": "Music",
        "genre": "Rock",
        "times": ["20:00"],
        "venue": "O2 Arena",
        "distance_km": 9.1,
        "url": "https://tm/rock",
        "price_min": 45.0,
        "price_max": 120.0,
        "currency": "GBP",
    }
    assert client.post("/api/v1/suggestions/events", json={"accommodation": BODY["accommodation"]}).status_code == 422
    fake.fail = True
    assert client.post("/api/v1/suggestions/events", json=BODY).status_code == 502


def test_events_need_a_ticketmaster_key() -> None:
    app.dependency_overrides.clear()
    with TestClient(app) as client:
        client.app.state.events_client = None
        assert client.post("/api/v1/suggestions/events", json=BODY).status_code == 503

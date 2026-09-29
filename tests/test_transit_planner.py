import asyncio
import json
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.services.geo import LatLng
from app.services.route_optimizer import order_day, plan_trip
from app.services.routes_client import (
    MatrixCell,
    RoutesAPIError,
    RoutesClient,
    TravelMode,
    parse_leg,
    parse_matrix,
)
from app.services.transit_planner import (
    TIMETABLE_HORIZON_DAYS,
    TRANSIT_MIN_SAVING_SECONDS,
    choose_leg,
    order_day_transit,
    timetable_day,
)
from tests.fake_routes import FakeTransitClient
from tests.test_route_optimizer import HOTEL, KM_LAT, make_poi, ring

PARIS_TZ = ZoneInfo("Europe/Paris")
WALK, TRANSIT = TravelMode.WALK, TravelMode.TRANSIT


def cell(minutes: float) -> MatrixCell:
    return MatrixCell(seconds=round(minutes * 60), meters=1000)


# --- walk or ride? ---------------------------------------------------------------------------


def test_short_walks_are_always_walked() -> None:
    choice = choose_leg(walk=cell(8), transit=cell(3))
    assert choice is not None and choice.mode is WALK
    assert choice.alternative == (TRANSIT, 180)  # quicker, so it is mentioned


def test_transit_is_taken_when_it_saves_enough_time() -> None:
    choice = choose_leg(walk=cell(40), transit=cell(20))
    assert choice is not None and choice.mode is TRANSIT
    assert choice.alternative == (WALK, 2400)
    # The ordering sees the waiting/transfer penalty, so it doesn't favour transit for nothing.
    assert choice.cost == 1200 + TRANSIT_MIN_SAVING_SECONDS


def test_a_small_saving_is_not_worth_the_ride() -> None:
    choice = choose_leg(walk=cell(20), transit=cell(17))
    assert choice is not None and choice.mode is WALK
    assert choice.alternative == (TRANSIT, 17 * 60)


@pytest.mark.parametrize("transit_minutes", [25, 20, 19])
def test_slower_or_barely_faster_transit_is_not_mentioned(transit_minutes: int) -> None:
    choice = choose_leg(walk=cell(20), transit=cell(transit_minutes))
    assert choice is not None and choice.mode is WALK and choice.alternative is None


def test_one_sided_and_missing_routes() -> None:
    only_transit = choose_leg(walk=None, transit=cell(15))
    assert only_transit is not None and only_transit.mode is TRANSIT and only_transit.alternative is None
    only_walk = choose_leg(walk=cell(45), transit=None)
    assert only_walk is not None and only_walk.mode is WALK and only_walk.alternative is None
    assert choose_leg(walk=None, transit=None) is None


# --- which timetable -----------------------------------------------------------------------------

TODAY = date(2026, 10, 1)


def test_timetable_day_without_dates_is_tomorrow() -> None:
    assert timetable_day(None, TODAY) == TODAY + timedelta(days=1)


def test_timetable_day_uses_near_dates_as_they_are() -> None:
    near = TODAY + timedelta(days=TIMETABLE_HORIZON_DAYS)
    assert timetable_day(near, TODAY) == near
    assert timetable_day(TODAY - timedelta(days=1), TODAY) == TODAY - timedelta(days=1)


@pytest.mark.parametrize("days_ahead", [TIMETABLE_HORIZON_DAYS + 1, 35, 36, 200])
def test_timetable_day_moves_far_dates_to_the_same_weekday_next_week(days_ahead: int) -> None:
    far = TODAY + timedelta(days=days_ahead)
    used = timetable_day(far, TODAY)
    assert used.weekday() == far.weekday()
    assert 1 <= (used - TODAY).days <= 7


# --- ordering a day ------------------------------------------------------------------------------


def east(km: float, north_km: float = 0.0) -> LatLng:
    """A point `km` east and `north_km` north of the hotel."""
    return LatLng(HOTEL.lat + north_km * KM_LAT, HOTEL.lng + km * KM_LAT / 0.658)


def test_a_day_mixes_walking_and_transit() -> None:
    client = FakeTransitClient()
    day = date.today() + timedelta(days=3)
    # A close stop (walked from the hotel) and two stops far east, next to each other.
    stops = [east(0.4), east(5.0), east(5.3, 0.3)]
    loop, transit_available = asyncio.run(order_day_transit(HOTEL, stops, [60, 90, 45], client, day, PARIS_TZ))

    assert transit_available
    assert sorted(loop.order) == [0, 1, 2]
    assert len(loop.legs) == 4
    modes = [leg.mode for leg in loop.legs]
    assert modes.count(TRANSIT) == 2  # out to the far pair and back from it
    assert loop.legs[0].mode is WALK or loop.legs[-1].mode is WALK  # the close stop is walked
    for leg in loop.legs:
        if leg.mode is TRANSIT:
            assert leg.rides and leg.rides[0].line == "M1"
            assert leg.alternative is not None and leg.alternative[0] is WALK
            assert leg.polyline == "transit-path"

    # Timetables: the transit matrix at midday of the trip day, walking without a time.
    matrix_departures = {mode: departure for mode, _, departure in client.matrix_calls}
    assert matrix_departures[WALK] is None
    assert matrix_departures[TRANSIT] == datetime.combine(day, time(12, 0), tzinfo=PARIS_TZ)


def test_legs_depart_when_the_traveller_leaves() -> None:
    client = FakeTransitClient()
    day = date.today() + timedelta(days=3)
    stops = [east(0.4), east(0.8)]
    visits = [60, 30]
    loop, _ = asyncio.run(order_day_transit(HOTEL, stops, visits, client, day, PARIS_TZ))

    departures = [departure for _, departure in client.leg_calls]
    start = datetime.combine(day, time(9, 0), tzinfo=PARIS_TZ)
    assert min(departures) == start
    # Each leg leaves after the previous leg's travel and the visit at its stop.
    path = [None, *loop.order]
    expected = [start]
    for leg, stop in zip(loop.legs, path[1:], strict=False):
        expected.append(expected[-1] + timedelta(seconds=leg.seconds, minutes=visits[stop]))
    assert sorted(departures) == expected


def test_without_transit_data_every_leg_is_walked() -> None:
    client = FakeTransitClient(has_transit=False)
    loop, transit_available = asyncio.run(
        order_day_transit(HOTEL, [east(3.0), east(-3.0)], [60, 60], client, None, PARIS_TZ)
    )
    assert not transit_available
    assert {leg.mode for leg in loop.legs} == {WALK}
    assert all(leg.alternative is None for leg in loop.legs)


def test_leg_routing_failure_keeps_the_matrix_times() -> None:
    client = FakeTransitClient(fail_legs=True)
    loop, _ = asyncio.run(order_day_transit(HOTEL, [east(0.4), east(5.0)], [60, 60], client, None, PARIS_TZ))
    assert all(leg.polyline is None and leg.seconds > 0 for leg in loop.legs)
    assert TRANSIT in {leg.mode for leg in loop.legs}


def test_matrix_failure_falls_back_to_estimates() -> None:
    routed = asyncio.run(order_day(HOTEL, ring(4), TRANSIT, FakeTransitClient(fail_matrix=True)))
    assert routed.source == "estimate"
    assert routed.transit_available is None
    assert all(leg.mode is None for leg in routed.loop.legs)


def test_plan_trip_in_transit_mode_returns_leg_details() -> None:
    client = FakeTransitClient()
    pois = [*ring(6, radius_km=4.0), make_poi("near", 0.3, category="NEAR")]
    days = asyncio.run(plan_trip(pois, HOTEL, 2, None, TRANSIT, client, tz=PARIS_TZ))
    assert all(d.routing_source == "google" and d.transit_available for d in days)
    legs = [s.leg_from_previous for d in days for s in d.stops] + [d.return_leg for d in days]
    assert all(leg is not None for leg in legs)
    rides = [ride for leg in legs if leg and leg.mode == "TRANSIT" for ride in leg.rides]
    assert rides and rides[0].vehicle == "SUBWAY" and rides[0].agency == "RATP"
    for day in days:
        assert day.total_travel_minutes == pytest.approx(
            sum(s.travel_minutes_from_previous for s in day.stops) + day.return_travel_minutes, abs=len(day.stops) + 1
        )


def test_walking_and_driving_plans_have_no_leg_details() -> None:
    [day] = asyncio.run(plan_trip(ring(4), HOTEL, 1, None, WALK, None))
    assert all(s.leg_from_previous is None for s in day.stops)
    assert day.return_leg is None and day.transit_available is None


# --- the Google client: parsing and request blocks -----------------------------------------------


def test_parse_matrix_reads_missing_indexes_as_zero_and_skips_missing_routes() -> None:
    elements = [
        {"status": {}, "condition": "ROUTE_NOT_FOUND"},  # 0 -> 0: indexes omitted, as Google does
        {"destinationIndex": 1, "status": {}, "condition": "ROUTE_EXISTS", "duration": "600s", "distanceMeters": 800},
        {"originIndex": 1, "status": {}, "condition": "ROUTE_EXISTS", "duration": "660s", "distanceMeters": 820},
        {"originIndex": 1, "destinationIndex": 1, "status": {"code": 5, "message": "not found"}},
    ]
    assert parse_matrix(elements, 2, 2) == [[None, MatrixCell(600, 800)], [MatrixCell(660, 820), None]]


def test_parse_leg_turns_transit_steps_into_rides() -> None:
    leg = {
        "duration": "2849s",
        "distanceMeters": 10858,
        "polyline": {"encodedPolyline": "abc"},
        "steps": [
            {"travelMode": "WALK", "staticDuration": "300s"},
            {
                "travelMode": "TRANSIT",
                "staticDuration": "660s",
                "transitDetails": {
                    "stopDetails": {"departureStop": {"name": "Sirkeci"}, "arrivalStop": {"name": "Söğütlüçeşme"}},
                    "headsign": "Gebze",
                    "stopCount": 3,
                    "transitLine": {
                        "name": "Halkalı - Gebze",
                        "nameShort": "B1 (Marmaray)",
                        "color": "#6a6c6e",
                        "textColor": "#ffffff",
                        "vehicle": {"type": "HEAVY_RAIL"},
                        "agencies": [{"name": "TCDD Taşımacılık"}],
                    },
                },
            },
            {"travelMode": "WALK", "staticDuration": "120s"},
        ],
    }
    parsed = parse_leg(leg)
    assert parsed.mode is TRANSIT
    assert (parsed.seconds, parsed.meters, parsed.polyline, parsed.walk_seconds) == (2849, 10858, "abc", 420)
    [ride] = parsed.rides
    assert (ride.vehicle, ride.line, ride.from_stop, ride.to_stop) == (
        "HEAVY_RAIL",
        "B1 (Marmaray)",
        "Sirkeci",
        "Söğütlüçeşme",
    )
    assert (ride.stop_count, ride.seconds, ride.headsign, ride.agency) == (3, 660, "Gebze", "TCDD Taşımacılık")


def test_parse_leg_without_rides_is_a_walk() -> None:
    parsed = parse_leg({"duration": "400s", "steps": [{"travelMode": "WALK", "staticDuration": "400s"}]})
    assert parsed.mode is WALK and parsed.rides == () and parsed.walk_seconds == 400


class FakeMatrixAPI:
    """Answers Route Matrix requests; element i -> j takes (i * 100 + j) seconds, where i is the
    origin's latitude (the tests put point i at latitude i)."""

    def __init__(self) -> None:
        self.bodies: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.bodies.append(body)
        lat = [round(o["waypoint"]["location"]["latLng"]["latitude"]) for o in body["origins"]]
        elements = [
            {
                "originIndex": row,
                "destinationIndex": col,
                "status": {},
                "condition": "ROUTE_EXISTS",
                "duration": f"{lat[row] * 100 + col}s",
                "distanceMeters": 1,
            }
            for row in range(len(body["origins"]))
            for col in range(len(body["destinations"]))
        ]
        return httpx.Response(200, json=elements)


def test_large_transit_matrices_are_requested_in_blocks() -> None:
    api = FakeMatrixAPI()
    client = RoutesClient("key", transport=httpx.MockTransport(api))
    points = [LatLng(i, 0) for i in range(11)]
    departure = datetime(2026, 10, 6, 12, 0, tzinfo=PARIS_TZ)
    matrix = asyncio.run(client.compute_matrix(points, TRANSIT, departure=departure))

    # 11 x 11 = 121 elements is over the transit limit of 100: 9 rows, then 2.
    assert sorted(len(body["origins"]) for body in api.bodies) == [2, 9]
    assert all(body["departureTime"] == "2026-10-06T10:00:00Z" for body in api.bodies)
    assert all(matrix[i][j] == MatrixCell(i * 100 + j, 1) for i in range(11) for j in range(11))


def test_walking_matrices_fit_one_request_and_carry_no_time() -> None:
    api = FakeMatrixAPI()
    client = RoutesClient("key", transport=httpx.MockTransport(api))
    asyncio.run(client.compute_matrix([LatLng(i, 0) for i in range(11)], WALK, departure=datetime.now(PARIS_TZ)))
    [body] = api.bodies
    assert "departureTime" not in body


def test_matrix_errors_raise() -> None:
    client = RoutesClient("key", transport=httpx.MockTransport(lambda _: httpx.Response(500, text="down")))
    with pytest.raises(RoutesAPIError):
        asyncio.run(client.compute_matrix([HOTEL, east(1)], TRANSIT))


def test_transit_order_cannot_be_optimized_by_google() -> None:
    client = RoutesClient("key", transport=httpx.MockTransport(lambda _: httpx.Response(500)))
    with pytest.raises(ValueError):
        asyncio.run(client.optimize_loop(HOTEL, [east(1)], TRANSIT))

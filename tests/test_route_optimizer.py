import asyncio
import math
from decimal import Decimal

import pytest

from app.models import POI
from app.services.geo import LatLng
from app.services.route_optimizer import (
    DAY_MINUTES,
    HotelTooFarError,
    estimate_loop,
    plan_trip,
    popularity,
    select_stops,
    split_into_days,
    stop_minutes,
)
from app.services.routes_client import Leg, LoopRoute, RoutesAPIError, TravelMode, _parse_duration

HOTEL = LatLng(48.8566, 2.3522)
MODE = TravelMode.DRIVE
KM_LAT = 1 / 111.32  # degrees of latitude per km


def make_poi(
    poi_id: str,
    dlat_km: float = 0.0,
    dlng_km: float = 0.0,
    *,
    name: str | None = None,
    category: str = "LANDMARK",
    duration: int = 60,
    rating: float | None = 4.5,
    reviews: int | None = 10_000,
    price: str | None = None,
) -> POI:
    """A POI placed dlat_km north and dlng_km east of the hotel (transient, never saved)."""
    return POI(
        id=poi_id,
        city_id="paris",
        place_id=poi_id,
        name=name or poi_id,
        category=category,
        latitude=HOTEL.lat + dlat_km * KM_LAT,
        longitude=HOTEL.lng + dlng_km * KM_LAT / 0.658,  # cos(48.86 deg) ~ 0.658
        avg_duration_min=duration,
        entry_price=Decimal(price) if price is not None else None,
        rating=rating,
        user_rating_count=reviews,
    )


def ring(n: int, radius_km: float = 2.0, **kwargs) -> list[POI]:
    """n POIs spread evenly on a circle around the hotel, with distinct categories and names."""
    return [
        make_poi(
            f"p{i}",
            radius_km * math.sin(2 * math.pi * i / n),
            radius_km * math.cos(2 * math.pi * i / n),
            category=f"CAT{i}",
            **kwargs,
        )
        for i in range(n)
    ]


# --- scoring & selection ---------------------------------------------------------------


def test_popularity_is_none_without_google_rating() -> None:
    assert popularity(make_poi("curated", rating=None, reviews=None)) is None
    assert popularity(make_poi("rated")) > 0


def test_popularity_grows_with_reviews() -> None:
    assert popularity(make_poi("famous", reviews=100_000)) > popularity(make_poi("local", reviews=500))


def test_selection_fits_time_capacity() -> None:
    chosen = select_stops(ring(40), HOTEL, days=2, budget=None, mode=MODE)
    assert chosen
    assert sum(stop_minutes(p, MODE) for p in chosen) <= 2 * DAY_MINUTES


def test_selection_respects_budget_and_treats_unknown_price_as_free() -> None:
    pois = [
        make_poi("a", 1, category="A", price="20"),
        make_poi("b", -1, category="B", price="20"),
        make_poi("c", 0, 1, category="C", price="20"),
        make_poi("free", 0, -1, category="D", price=None),
    ]
    chosen = select_stops(pois, HOTEL, days=1, budget=Decimal("45"), mode=MODE)
    ids = {p.id for p in chosen}
    assert "free" in ids
    assert sum(p.entry_price or 0 for p in chosen) <= 45
    assert len(ids & {"a", "b", "c"}) == 2


def test_selection_prefers_close_over_far_at_equal_popularity() -> None:
    near = make_poi("near", 1, category="A", duration=400)
    far = make_poi("far", 15, category="B", duration=400)
    assert select_stops([far, near], HOTEL, days=1, budget=None, mode=MODE) == [near]


def test_selection_skips_near_duplicate_sights() -> None:
    louvre = make_poi("louvre", 0.5, name="Louvre Museum", category="MUSEUM", reviews=300_000)
    pyramid = make_poi("pyramid", 0.6, name="Louvre Pyramid", reviews=100_000)
    # Close by, but different sights (no shared distinctive word).
    neighbour = make_poi("other", 0.55, name="Tuileries Garden", category="PARK", reviews=100_000)
    ids = {p.id for p in select_stops([louvre, pyramid, neighbour], HOTEL, 1, None, MODE)}
    assert ids == {"louvre", "other"}


def test_category_decay_keeps_the_trip_varied() -> None:
    churches = [make_poi(f"church{i}", 1, i * 0.3, category="RELIGIOUS_SITE", reviews=50_000) for i in range(5)]
    parks = [make_poi(f"park{i}", -1, i * 0.3, category="PARK", reviews=20_000) for i in range(2)]
    chosen = select_stops(churches + parks, HOTEL, days=1, budget=None, mode=MODE)
    categories = [p.category for p in chosen]
    assert "PARK" in categories
    assert categories.count("RELIGIOUS_SITE") < 5


# --- splitting into days -----------------------------------------------------------------


def test_split_uses_every_stop_once_and_fills_every_day() -> None:
    stops = ring(12)
    groups = split_into_days(stops, HOTEL, days=3, mode=MODE)
    assert len(groups) == 3
    assert all(groups)
    assert sorted(p.id for g in groups for p in g) == sorted(p.id for p in stops)


def test_split_keeps_each_direction_on_one_day() -> None:
    east = [make_poi(f"e{i}", i * 0.2, 3) for i in range(3)]
    west = [make_poi(f"w{i}", i * 0.2, -3) for i in range(3)]
    groups = split_into_days(east + west, HOTEL, days=2, mode=MODE)
    assert sorted({p.id[0] for p in g} for g in groups) == [{"e"}, {"w"}]


def test_split_pads_with_empty_days_when_stops_run_out() -> None:
    groups = split_into_days(ring(2), HOTEL, days=4, mode=MODE)
    assert len(groups) == 4
    assert [len(g) for g in groups] == [1, 1, 0, 0]


# --- ordering ------------------------------------------------------------------------------


def test_estimate_loop_visits_nearest_first_and_returns_to_hotel() -> None:
    points = [LatLng(HOTEL.lat + d * KM_LAT, HOTEL.lng) for d in (3, 1, 2)]
    loop = estimate_loop(HOTEL, points, MODE)
    assert loop.order == [1, 2, 0]
    assert len(loop.legs) == len(points) + 1
    assert all(leg.seconds > 0 for leg in loop.legs)


def test_parse_duration() -> None:
    assert _parse_duration("754s") == 754
    assert _parse_duration("0s") == 0


# --- end to end (with a fake Google client) ----------------------------------------------------


class FakeRoutesClient:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    async def optimize_loop(self, origin: LatLng, stops: list[LatLng], mode: TravelMode) -> LoopRoute:
        self.calls += 1
        if self.fail:
            raise RoutesAPIError("boom")
        order = list(reversed(range(len(stops))))
        return LoopRoute(order=order, legs=[Leg(seconds=600, meters=2000, polyline="enc")] * (len(stops) + 1))


def test_plan_trip_uses_google_ordering() -> None:
    client = FakeRoutesClient()
    days = asyncio.run(plan_trip(ring(12), HOTEL, 2, None, MODE, client))
    assert client.calls == 2
    assert [d.routing_source for d in days] == ["google", "google"]
    for day in days:
        assert [s.order_in_day for s in day.stops] == list(range(1, len(day.stops) + 1))
        assert day.total_travel_minutes == 10 * (len(day.stops) + 1)
        assert all(s.path_from_previous == "enc" for s in day.stops)
        assert day.return_path == "enc"


def test_plan_trip_falls_back_to_estimates_when_google_fails() -> None:
    days = asyncio.run(plan_trip(ring(12), HOTEL, 2, None, MODE, FakeRoutesClient(fail=True)))
    assert {d.routing_source for d in days} == {"estimate"}
    assert all(d.stops for d in days)
    # No street geometry for estimates: the map draws straight lines instead.
    assert all(s.path_from_previous is None for d in days for s in d.stops)


def test_plan_trip_works_without_google_client() -> None:
    days = asyncio.run(plan_trip(ring(6), HOTEL, 1, None, TravelMode.WALK, None))
    assert days[0].routing_source == "estimate"


def test_plan_trip_rejects_hotel_outside_the_city() -> None:
    with pytest.raises(HotelTooFarError):
        asyncio.run(plan_trip(ring(6), LatLng(41.0, 28.9), 1, None, MODE, None))

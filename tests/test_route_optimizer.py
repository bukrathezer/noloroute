import asyncio
import json
import math
from datetime import date
from decimal import Decimal

import pytest

from app.models import POI
from app.services.geo import LatLng
from app.services.route_optimizer import (
    DAY_MINUTES,
    MAX_DAY_MINUTES,
    MAX_TRIMS_PER_DAY,
    HotelTooFarError,
    build_day,
    estimate_loop,
    fill_days,
    fit_to_dates,
    location,
    loop_minutes,
    order_day,
    plan_trip,
    popularity,
    select_stops,
    split_into_days,
    stop_minutes,
)
from app.services.routes_client import Leg, LoopRoute, RoutesAPIError, TravelMode, _parse_duration
from app.services.weather import DayWeather

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
    hours: str | None = None,
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
        opening_hours=hours,
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


def test_selection_skips_a_second_listing_at_the_same_spot() -> None:
    bazaar = make_poi("bazaar", 0.5, name="Egyptian Bazaar", category="MARKET", reviews=190_000)
    listing = make_poi("listing", 0.5001, name="Mercado egipcio", category="MARKET", reviews=2_000)
    # Next door, but another kind of place.
    mosque = make_poi("mosque", 0.5002, name="New Mosque", category="RELIGIOUS_SITE", reviews=40_000)
    ids = {p.id for p in select_stops([bazaar, listing, mosque], HOTEL, 1, None, MODE)}
    assert ids == {"bazaar", "mosque"}


def test_selection_skips_listings_of_the_same_wikidata_item() -> None:
    mosque = make_poi("mosque", 0.5, name="Şişli Camii", category="RELIGIOUS_SITE", reviews=9_000)
    foundation = make_poi("foundation", 0.6, name="Şişli Cami Şerifi Vakfı", category="RELIGIOUS_SITE", reviews=900)
    mosque.wikidata_id = foundation.wikidata_id = "Q6061170"
    assert [p.id for p in select_stops([mosque, foundation], HOTEL, 1, None, MODE)] == ["mosque"]


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
    # Each side on a day of its own (in either order).
    assert sorted("".join(sorted({p.id[0] for p in g})) for g in groups) == ["e", "w"]


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


# --- dates, opening hours and rain -----------------------------------------------------------------

TUESDAY = date(2026, 10, 6)
WEDNESDAY = date(2026, 10, 7)
# Open 09:00-18:00 every day except Tuesday (Google day 2), like the Louvre.
CLOSED_TUESDAYS = json.dumps(
    [
        {"open": {"day": d, "hour": 9, "minute": 0}, "close": {"day": d, "hour": 18, "minute": 0}}
        for d in (0, 1, 3, 4, 5, 6)
    ]
)


def weather(day: date, rainy: bool) -> DayWeather:
    return DayWeather(
        day=day,
        source="forecast",
        condition="rain" if rainy else "clear",
        temp_max_c=20.0,
        temp_min_c=12.0,
        precipitation_chance=80 if rainy else 5,
        is_rainy=rainy,
    )


def test_a_stop_moves_off_the_day_it_is_closed() -> None:
    museum = make_poi("museum", 1, category="MUSEUM", hours=CLOSED_TUESDAYS)
    park = make_poi("park", -1, category="PARK")
    groups, _ = fit_to_dates([[museum], [park]], [TUESDAY, WEDNESDAY], [False, False], MODE)
    assert [[p.id for p in g] for g in groups] == [[], ["park", "museum"]]


def test_a_stop_closed_on_every_trip_day_is_dropped() -> None:
    museum = make_poi("museum", 1, category="MUSEUM", hours=CLOSED_TUESDAYS)
    groups, _ = fit_to_dates([[museum]], [TUESDAY], [False], MODE)
    assert groups == [[]]


def test_rain_moves_outdoor_stops_to_a_dry_day() -> None:
    park = make_poi("park", 1, category="PARK")
    museum = make_poi("museum", 1.2, category="MUSEUM")
    church = make_poi("church", -1, category="RELIGIOUS_SITE")
    groups, adjusted = fit_to_dates([[park, museum], [church]], [TUESDAY, WEDNESDAY], [True, False], MODE)
    assert [[p.id for p in g] for g in groups] == [["museum"], ["church", "park"]]
    assert adjusted == [True, False]


def test_without_a_dry_day_outdoor_stops_stay() -> None:
    park = make_poi("park", 1, category="PARK")
    groups, adjusted = fit_to_dates([[park], []], [TUESDAY, WEDNESDAY], [True, True], MODE)
    assert [[p.id for p in g] for g in groups] == [["park"], []]
    assert adjusted == [False, False]


def test_a_rainy_trip_prefers_indoor_sights() -> None:
    # Only one of the two fits in a day; the park is slightly more popular.
    park = make_poi("park", 1, category="PARK", duration=400, reviews=11_000)
    museum = make_poi("museum", 1, category="MUSEUM", duration=400, reviews=10_000)
    assert [p.id for p in select_stops([park, museum], HOTEL, 1, None, MODE)] == ["park"]
    assert [p.id for p in select_stops([park, museum], HOTEL, 1, None, MODE, rainy_share=1.0)] == ["museum"]


def test_plan_trip_with_dates_adds_dates_hours_and_weather() -> None:
    museum = make_poi("museum", 1, category="MUSEUM", hours=CLOSED_TUESDAYS, reviews=500_000)
    others = ring(6)
    days = asyncio.run(
        plan_trip(
            [museum, *others],
            HOTEL,
            1,
            None,
            MODE,
            None,
            dates=[TUESDAY],
            weather=[weather(TUESDAY, rainy=True)],
        )
    )
    [day] = days
    assert day.date == TUESDAY
    assert day.weather is not None and day.weather.is_rainy and day.weather.condition == "rain"
    assert "museum" not in [s.poi_id for s in day.stops]  # closed on Tuesdays, despite its popularity
    assert day.stops  # the rest of the day is still planned


def test_plan_trip_shows_hours_for_the_day() -> None:
    museum = make_poi("museum", 1, category="MUSEUM", hours=CLOSED_TUESDAYS, reviews=500_000)
    [day] = asyncio.run(plan_trip([museum, *ring(4)], HOTEL, 1, None, MODE, None, dates=[WEDNESDAY]))
    hours = {s.poi_id: s.hours for s in day.stops}
    assert hours["museum"] == "09:00–18:00"
    assert hours["p0"] is None  # no hours known for the ring POIs
    assert day.weather is None  # no weather given


def test_plan_trip_without_dates_is_unchanged() -> None:
    [day] = asyncio.run(plan_trip(ring(6), HOTEL, 1, None, MODE, None))
    assert day.date is None and day.weather is None and not day.rain_adjusted
    assert all(s.hours is None for s in day.stops)


# --- keeping clusters together and days short enough --------------------------------------------


def test_a_cluster_of_sights_stays_on_one_day() -> None:
    # Four sights together 3 km north, and four scattered right around the hotel. Sorting by
    # direction alone would cut the northern cluster in half; cutting a round trip keeps it whole.
    cluster = [make_poi(f"x{i}", 3.0 + 0.1 * (i % 2), 0.15 * (i - 1.5), category=f"X{i}") for i in range(4)]
    around = [make_poi(f"n{i}", dlat, dlng, category=f"N{i}") for i, (dlat, dlng) in
              enumerate([(0.4, 0.4), (-0.4, 0.4), (-0.4, -0.4), (0.4, -0.4)])]  # fmt: skip
    groups = split_into_days(cluster + around, HOTEL, days=2, mode=MODE)
    days_of_cluster = {d for d, group in enumerate(groups) for p in group if p.id.startswith("x")}
    assert len(days_of_cluster) == 1
    assert [len(g) for g in groups] == [4, 4]


def long_day(n: int, duration: int) -> list[POI]:
    """n stops close to the hotel, the first one the least popular."""
    return [make_poi(f"s{i}", 0.3 * (i + 1), category=f"C{i}", duration=duration, reviews=1_000 * (i + 1))
            for i in range(n)]  # fmt: skip


def test_a_day_that_runs_long_drops_its_least_popular_stop() -> None:
    stops = long_day(4, duration=120)  # 8 h of visits plus 5 legs of 10 min: 8 h 50 min
    client = FakeRoutesClient()
    routed = asyncio.run(order_day(HOTEL, stops, MODE, client))
    assert sorted(routed.loop.order) == [1, 2, 3]  # s0, the least popular, is gone
    assert client.calls == 2  # routed once more without it
    day = build_day(1, stops, routed)
    assert day.dropped_stops == ["s0"]
    assert day.total_visit_minutes + day.total_travel_minutes <= MAX_DAY_MINUTES


def test_hand_picked_must_sees_are_dropped_last() -> None:
    stops = long_day(4, duration=120)
    stops[0] = make_poi("montmartre", 0.3, category="C0", duration=120, rating=None, reviews=None)
    routed = asyncio.run(order_day(HOTEL, stops, MODE, FakeRoutesClient()))
    assert 0 in routed.loop.order
    assert build_day(1, stops, routed).dropped_stops == ["s1"]


def test_trimming_stops_after_a_few_rounds() -> None:
    client = FakeRoutesClient()
    routed = asyncio.run(order_day(HOTEL, long_day(6, duration=200), MODE, client))
    assert client.calls == MAX_TRIMS_PER_DAY + 1  # every round costs a Google request
    assert len(routed.loop.order) == 6 - MAX_TRIMS_PER_DAY


def test_estimated_days_are_trimmed_too() -> None:
    routed = asyncio.run(order_day(HOTEL, long_day(5, duration=110), MODE, None))  # 9 h 10 min of visits
    assert routed.source == "estimate"
    assert len(routed.loop.order) == 4


# --- filling days that have time left ------------------------------------------------------------


def test_a_short_day_gets_the_best_sights_that_still_fit() -> None:
    chosen = make_poi("chosen", 0.5, category="A", duration=120)
    famous = make_poi("famous", 0.6, category="B", duration=60, reviews=200_000)
    other = make_poi("other", -0.5, category="C", duration=60, reviews=20_000)
    too_long = make_poi("too-long", 0.4, category="D", duration=400, reviews=900_000)
    [day] = fill_days([[chosen]], [chosen, famous, other, too_long], HOTEL, MODE, None)
    assert {p.id for p in day} == {"chosen", "famous", "other"}  # the 400-minute one doesn't fit
    assert loop_minutes(day, estimate_loop(HOTEL, [location(p) for p in day], MODE)) <= DAY_MINUTES


def test_filling_respects_hours_rain_budget_and_duplicates() -> None:
    chosen = make_poi("louvre", 0.5, name="Louvre Museum", category="MUSEUM", duration=60, price="30")
    closed = make_poi("closed", 0.6, category="A", hours=CLOSED_TUESDAYS)
    park = make_poi("park", 0.6, category="PARK")
    pricey = make_poi("pricey", 0.6, category="B", price="50")
    pyramid = make_poi("pyramid", 0.52, name="Louvre Pyramid", category="C")
    fine = make_poi("fine", -0.6, category="D", reviews=100)
    pois = [chosen, closed, park, pricey, pyramid, fine]
    [day] = fill_days([[chosen]], pois, HOTEL, MODE, Decimal("60"), dates=[TUESDAY], rainy=[True])
    assert {p.id for p in day} == {"louvre", "fine"}


def test_filling_varies_categories() -> None:
    chosen = make_poi("m0", 0.5, category="MUSEUM", duration=60)
    museum = make_poi("m1", 0.6, category="MUSEUM", duration=250, reviews=12_000)
    park = make_poi("p1", 0.6, category="PARK", duration=250, reviews=10_000)  # only one of the two fits
    [day] = fill_days([[chosen]], [chosen, museum, park], HOTEL, MODE, None)
    assert [p.id for p in day if p.id != "m0"] == ["p1"]  # slightly less popular, but a new category

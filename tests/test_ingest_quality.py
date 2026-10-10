"""What the ingestion keeps out (shops, second listings) and adds back (famous sights it missed)."""

import math
from collections import Counter

import pytest

import scripts.ingest_places as ingest
from app.services.geo import LatLng
from app.services.places_client import BoundingBox
from app.services.wikipedia import FamousPlace
from scripts.ingest_places import CityConfig, build_rows, drop_same_spot, find_famous_sights

KM_PER_DEG_LAT = 111.32
CENTRE = LatLng(51.5074, -0.1278)
BOUNDS = BoundingBox(51.40, -0.30, 51.62, 0.05)
CITY = CityConfig("london", "London", "GBP", "Europe/London", BOUNDS)


def north_of(where: LatLng, metres: float) -> LatLng:
    return LatLng(where.lat + metres / 1000 / KM_PER_DEG_LAT, where.lng)


def place(pid: str, name: str, at: LatLng, reviews: int, primary: str, *types: str) -> dict:
    return {
        "id": pid,
        "displayName": {"text": name},
        "location": {"latitude": at.lat, "longitude": at.lng},
        "types": [primary, *types],
        "primaryType": primary,
        "userRatingCount": reviews,
        "businessStatus": "OPERATIONAL",
    }


def raw(*places: dict) -> list[dict]:
    return [{"source": "test", "place": p} for p in places]


def names(rows: list[dict]) -> set[str]:
    return {r["name"] for r in rows}


def test_markets_that_are_shops_are_left_out() -> None:
    rows = build_rows(
        raw(
            place("a", "Testaccio Market", north_of(CENTRE, 0), 8936, "market"),
            place("b", "Feriköy Antika Pazarı", north_of(CENTRE, 500), 2461, "flea_market", "market"),
            place("c", "Grand Bazaar", north_of(CENTRE, 1000), 190_000, "market", "tourist_attraction", "store"),
            # A second-hand shop chain, by its shop types or by its name.
            place(
                "d", "Mercatino Franchising Porta Maggiore", north_of(CENTRE, 1500), 3413, "flea_market", "book_store"
            ),
            place("e", "Mercatino Usato Roma Viale Tirreno", north_of(CENTRE, 2000), 5299, "flea_market", "market"),
            place("f", "CONAD", north_of(CENTRE, 2500), 1029, "market", "supermarket", "grocery_store"),
        ),
        CITY,
    )
    assert names(rows) == {"Testaccio Market", "Feriköy Antika Pazarı", "Grand Bazaar"}


def test_a_second_listing_at_the_same_spot_is_left_out() -> None:
    bazaar = place("a", "Egyptian Bazaar", CENTRE, 190_000, "market")
    listing = place("b", "Mercado egipcio", north_of(CENTRE, 2), 2_093, "market")
    mosque = place("c", "New Mosque", north_of(CENTRE, 5), 40_000, "mosque")  # next door, another kind
    market = place("d", "Flower Market", north_of(CENTRE, 100), 9_000, "market")  # same kind, further off
    assert names(build_rows(raw(bazaar, listing, mosque, market), CITY)) == {
        "Egyptian Bazaar",
        "New Mosque",
        "Flower Market",
    }


def test_drop_same_spot_keeps_the_most_reviewed_listing() -> None:
    rows = [
        {"name": "small", "category": "MUSEUM", "latitude": 51.5, "longitude": 0.0, "user_rating_count": 900},
        {"name": "big", "category": "MUSEUM", "latitude": 51.5001, "longitude": 0.0, "user_rating_count": 90_000},
    ]
    assert names(drop_same_spot(rows)) == {"big"}


class FakeWiki:
    def __init__(self, famous: list[FamousPlace]) -> None:
        self.famous = famous

    def famous_places(self, centre: LatLng, radius_km: float) -> list[FamousPlace]:
        return self.famous


class FakePlaces:
    """Text Search answers by name; every call is counted."""

    def __init__(self, answers: dict[str, dict]) -> None:
        self.answers = answers
        self.requests: Counter[str] = Counter()

    def find_place_near(self, query: str, near: LatLng, radius_m: float) -> dict | None:
        self.requests["text"] += 1
        return self.answers.get(query)


def famous(qid: str, label: str, where: LatLng, links: int = 100) -> FamousPlace:
    return FamousPlace(qid, label, "museum", links, where)


BRITISH_MUSEUM = north_of(CENTRE, 1200)
LOUVRE_LIKE = north_of(CENTRE, -800)


def known_row(name: str, where: LatLng) -> dict:
    return {"place_id": f"id-{name}", "name": name, "latitude": where.lat, "longitude": where.lng}


def test_famous_sights_the_search_missed_are_added() -> None:
    client = FakePlaces(
        {
            # Few reviews on Google, many Wikipedias: the case the popularity search misses.
            "British Museum": place("bm", "The British Museum", north_of(BRITISH_MUSEUM, 20), 3064, "museum"),
            # Google finds something of that name, but far from the sight.
            "Tower Bridge": place("tb", "Tower Bridge Café", north_of(CENTRE, 6000), 900, "museum"),
            # Not a sightseeing type.
            "Gherkin": place("g", "30 St Mary Axe", north_of(CENTRE, 2500), 5000, "corporate_office"),
        }
    )
    wiki = FakeWiki(
        [
            famous("Q6373", "British Museum", BRITISH_MUSEUM, links=130),
            # Already have it, right there: not even looked up.
            famous("Q19675", "Old Gallery", north_of(LOUVRE_LIKE, 30)),
            famous("Q83125", "Tower Bridge", north_of(CENTRE, 2000)),
            famous("Q194422", "Gherkin", north_of(CENTRE, 2500)),
        ]
    )
    found = find_famous_sights(client, wiki, "london", BOUNDS, [known_row("Old Gallery", LOUVRE_LIKE)])
    assert [item["place"]["displayName"]["text"] for item in found] == ["The British Museum"]
    assert client.requests["text"] == 3


def test_famous_sights_stop_at_the_lookup_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ingest, "FAMOUS_MAX_LOOKUPS", 2)
    sights = [famous(f"Q{i}", f"Sight {i}", north_of(CENTRE, 1000 * i)) for i in range(1, 6)]
    client = FakePlaces({})
    find_famous_sights(client, FakeWiki(sights), "london", BOUNDS, [])
    assert client.requests["text"] == 2


def test_famous_sights_outside_the_city_are_skipped() -> None:
    far_away = LatLng(BOUNDS.north + 0.5, CENTRE.lng)
    client = FakePlaces({"Windsor Castle": place("w", "Windsor Castle", far_away, 60_000, "castle")})
    assert find_famous_sights(client, FakeWiki([famous("Q1", "Windsor Castle", far_away)]), "london", BOUNDS, []) == []
    assert client.requests["text"] == 0


def test_the_extent_of_rows_is_widened() -> None:
    rows = [known_row("a", LatLng(41.0, 29.0)), known_row("b", LatLng(41.1, 29.1))]
    box = ingest._extent(rows, pad_km=1.0)
    assert box.south < 41.0 and box.north > 41.1 and box.west < 29.0 and box.east > 29.1
    assert math.isclose(box.north - 41.1, 1 / KM_PER_DEG_LAT)

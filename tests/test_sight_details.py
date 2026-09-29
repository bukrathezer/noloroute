from decimal import Decimal

from app.models.poi import POICategory
from scripts.ingest_places import CITIES, build_rows
from scripts.sight_details import (
    CITY_PRICES,
    FAME_BASE_REVIEWS,
    SIGHTS,
    estimate_entry_price,
    estimate_visit_minutes,
)

LOUVRE = "ChIJD3uTd9hx5kcR1IQvGfr8dbk"
LOUVRE_PYRAMID = "ChIJQdQyeiZu5kcRUfQHfB-OCLA"

# --- rules -------------------------------------------------------------------------------------


def test_visit_time_follows_the_kind_of_place() -> None:
    statue = estimate_visit_minutes("sculpture", POICategory.LANDMARK, FAME_BASE_REVIEWS)
    square = estimate_visit_minutes("plaza", POICategory.LANDMARK, FAME_BASE_REVIEWS)
    palace = estimate_visit_minutes("castle", POICategory.LANDMARK, FAME_BASE_REVIEWS)
    assert statue < square < palace
    assert (statue, palace) == (10, 90)


def test_famous_places_take_longer_within_bounds() -> None:
    def museum(reviews: int) -> int:
        return estimate_visit_minutes("museum", POICategory.MUSEUM, reviews)

    assert museum(500) < museum(FAME_BASE_REVIEWS) < museum(100_000)
    assert museum(10) == museum(500) == 70  # x0.75 at most ...
    assert museum(10_000_000) == 135  # ... and x1.5


def test_places_without_a_type_use_their_category() -> None:
    assert estimate_visit_minutes(None, POICategory.MARKET, FAME_BASE_REVIEWS) == 45
    assert estimate_visit_minutes("not_a_known_type", POICategory.MUSEUM, None) == 90


def test_free_types_cost_nothing_and_the_rest_is_unknown() -> None:
    assert estimate_entry_price("park") == Decimal(0)
    assert estimate_entry_price("mosque") == Decimal(0)
    assert estimate_entry_price("museum") is None
    assert estimate_entry_price(None) is None


# --- the hand-checked table -------------------------------------------------------------------------


def test_same_as_entries_point_at_a_real_sight() -> None:
    for place_id, sight in SIGHTS.items():
        if sight.same_as:
            target = SIGHTS.get(sight.same_as)
            assert target is not None and target.same_as is None, place_id
            assert sight.visit_minutes is None and sight.entry_price is None, place_id


def test_hand_checked_values_are_sensible() -> None:
    for place_id, sight in SIGHTS.items():
        assert sight.entry_price is None or sight.entry_price >= 0, place_id
        assert sight.visit_minutes is None or 10 <= sight.visit_minutes <= 240, place_id
    assert set(CITY_PRICES) <= set(CITIES)


# --- ingestion ---------------------------------------------------------------------------------------


def place(place_id: str, name: str, primary_type: str | None, reviews: int = 5_000) -> dict:
    return {
        "source": "test",
        "place": {
            "id": place_id,
            "displayName": {"text": name},
            "location": {"latitude": 48.86, "longitude": 2.34},  # inside Paris
            "primaryType": primary_type,
            "types": [primary_type] if primary_type else [],
            "rating": 4.5,
            "userRatingCount": reviews,
            "businessStatus": "OPERATIONAL",
        },
    }


def test_ingestion_applies_rules_overrides_and_skips_parts_of_other_sights() -> None:
    raw = [
        place(LOUVRE, "Louvre Museum", "art_museum", 378_000),
        place(LOUVRE_PYRAMID, "Louvre Pyramid", "cultural_landmark", 85_000),
        place("some-park", "Small Park", "park", 1_000),
        place("some-museum", "Small Museum", "museum", 2_000),
    ]
    rows = {row["place_id"]: row for row in build_rows(raw, CITIES["paris"])}

    assert LOUVRE_PYRAMID not in rows  # part of the Louvre
    louvre = rows[LOUVRE]
    assert (louvre["avg_duration_min"], louvre["entry_price"]) == (180, Decimal("32"))
    assert louvre["google_type"] == "art_museum"
    assert rows["some-park"]["entry_price"] == Decimal(0)
    assert rows["some-museum"]["entry_price"] is None
    assert rows["some-museum"]["avg_duration_min"] == estimate_visit_minutes("museum", POICategory.MUSEUM, 2_000)
    curated = [row for row in rows.values() if row["place_id"].startswith("curated:")]
    assert curated and all(row["entry_price"] == Decimal(0) for row in curated)

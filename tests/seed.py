"""Test data shared by the database-backed tests."""

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import POI, City

CITY_ID = "test-city"
HOTEL = {"lat": 48.8566, "lng": 2.3522}
POI_COUNT = 12
PRICES_CHECKED_ON = date(2026, 9, 1)


def seed_city(session: Session) -> None:
    """A small city whose POIs sit around HOTEL; half of them have an entry price."""
    session.add(
        City(
            id=CITY_ID,
            name="Test City",
            name_tr="Test Şehri",
            country_code="FR",
            currency_code="EUR",
            timezone="Europe/Paris",
            price_basis="adult",
            prices_checked_on=PRICES_CHECKED_ON,
        )
    )
    for i in range(POI_COUNT):
        session.add(
            POI(
                city_id=CITY_ID,
                place_id=f"test-place-{i}",
                name=f"Sight {i}",
                category=["MUSEUM", "PARK", "LANDMARK"][i % 3],
                latitude=HOTEL["lat"] + (i % 4 - 1.5) * 0.01,
                longitude=HOTEL["lng"] + (i // 4 - 1) * 0.015,
                avg_duration_min=60,
                entry_price=Decimal("10.00") if i % 2 == 0 else None,
                rating=4.5,
                user_rating_count=1000 + i * 100,
            )
        )
    session.flush()

"""Visit times and entry prices for sights, used by the ingestion script.

Google Places has neither, so they are set here in two layers:

1. Rules for every sight: a visit time from its Google type (a statue is quick, a palace is not)
   scaled by how famous it is (well-known places tend to be bigger and busier), and a price of
   zero for types that are free to visit (parks, squares, mosques, ...).
2. Hand-checked values for the most visited sights (SIGHTS): typical visit times, and entry
   prices from the official sites or recent news, checked on PRICES_CHECKED_ON. Some Google
   entries are part of another sight (the Louvre Pyramid is the Louvre's entrance); these are
   marked `same_as` and left out, so a plan never visits (and pays for) the same place twice.

Prices are adult tickets in the city's currency (CITY_PRICES says which ticket): in Paris the
price for visitors from outside the EU, which several museums raised in 2026; in Istanbul the
price for Turkish citizens (foreign visitors pay more). Where prices change with the season, the
higher one is used, so budgets err on the safe side. None means the price is unknown.
"""

import math
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from app.models.poi import POICategory

# --- rules --------------------------------------------------------------------------------------

# Minutes for a visit to a place of that Google primary type with FAME_BASE_REVIEWS reviews.
TYPE_VISIT_MINUTES: dict[str, int] = {
    "museum": 90,
    "art_museum": 90,
    "history_museum": 75,
    "art_gallery": 45,
    "castle": 90,
    "palace": 90,
    "opera_house": 60,
    "historical_landmark": 45,
    "historical_place": 45,
    "cultural_landmark": 30,
    "tourist_attraction": 30,
    "monument": 30,
    "cemetery": 45,
    "plaza": 20,
    "bridge": 15,
    "fountain": 10,
    "sculpture": 10,
    "park": 45,
    "city_park": 45,
    "garden": 45,
    "botanical_garden": 60,
    "national_park": 90,
    "church": 30,
    "mosque": 30,
    "synagogue": 30,
    "hindu_temple": 30,
    "buddhist_temple": 45,
    "shinto_shrine": 30,
    "place_of_worship": 30,
    "observation_deck": 45,
    "scenic_spot": 20,
    "market": 45,
    "flea_market": 60,
    "aquarium": 90,
}
# For places without a primary type (Google leaves it out for some famous ones).
CATEGORY_VISIT_MINUTES: dict[POICategory, int] = {
    POICategory.MUSEUM: 90,
    POICategory.LANDMARK: 45,
    POICategory.PARK: 45,
    POICategory.RELIGIOUS_SITE: 30,
    POICategory.VIEWPOINT: 30,
    POICategory.MARKET: 45,
    POICategory.OTHER: 45,
}
FAME_BASE_REVIEWS = 10_000
FAME_STEP = 0.3  # every 10x more reviews adds 30% to the visit ...
FAME_MIN, FAME_MAX = 0.75, 1.5  # ... within these bounds
MIN_VISIT_MINUTES = 10

# Types that are free to enter. Exceptions (a paid chapel, a botanical garden's greenhouses)
# are listed in SIGHTS.
FREE_TYPES = {
    "park",
    "city_park",
    "garden",
    "national_park",
    "plaza",
    "bridge",
    "fountain",
    "sculpture",
    "scenic_spot",
    "church",
    "mosque",
    "synagogue",
    "hindu_temple",
    "shinto_shrine",
    "place_of_worship",
    "cemetery",
    "market",
    "flea_market",
}


def estimate_visit_minutes(google_type: str | None, category: POICategory, review_count: int | None) -> int:
    base = TYPE_VISIT_MINUTES.get(google_type or "", CATEGORY_VISIT_MINUTES[category])
    reviews = max(review_count or FAME_BASE_REVIEWS, 1)
    fame = min(max(1 + FAME_STEP * math.log10(reviews / FAME_BASE_REVIEWS), FAME_MIN), FAME_MAX)
    return max(MIN_VISIT_MINUTES, 5 * round(base * fame / 5))


def estimate_entry_price(google_type: str | None) -> Decimal | None:
    """Zero for types that are free to visit; None (unknown) for everything else."""
    return Decimal(0) if google_type in FREE_TYPES else None


# --- hand-checked values -------------------------------------------------------------------------

PriceBasis = Literal["adult", "tr_citizen"]


@dataclass(frozen=True)
class CityPrices:
    basis: PriceBasis  # "adult": standard adult ticket; "tr_citizen": the Turkish citizens' price
    checked_on: date


PRICES_CHECKED_ON = date(2026, 9, 29)
CITY_PRICES: dict[str, CityPrices] = {
    "paris": CityPrices("adult", PRICES_CHECKED_ON),
    "istanbul": CityPrices("tr_citizen", PRICES_CHECKED_ON),
}


@dataclass(frozen=True)
class Sight:
    name: str  # for reading this table; matching uses the Google place ID
    visit_minutes: int | None = None
    entry_price: Decimal | None = None
    same_as: str | None = None  # place ID of the sight this entry is part of: left out
    source: str | None = None  # where the price comes from


# Keyed by Google place ID.
SIGHTS: dict[str, Sight] = {
    # --- Paris ---
    "ChIJLU7jZClu5kcR4PcOOO6p3I0": Sight(
        "Eiffel Tower",
        150,
        Decimal("36.70"),
        source="2026 summit-by-lift rate, per ticket guides (official site blocks bots)",
    ),
    "ChIJD3uTd9hx5kcR1IQvGfr8dbk": Sight(
        "Louvre Museum", 180, Decimal("32"), source="non-EEA rate since 14 Jan 2026 (CNN, 28 Nov 2025)"
    ),
    "ChIJQdQyeiZu5kcRUfQHfB-OCLA": Sight("Louvre Pyramid", same_as="ChIJD3uTd9hx5kcR1IQvGfr8dbk"),
    "ChIJjx37cOxv5kcRPWQuEW5ntdk": Sight(
        "Arc de Triomphe", 60, Decimal("22"), source="paris-arc-de-triomphe.fr: Apr-Sep (16 Oct-Mar)"
    ),
    "ChIJG5Qwtitu5kcR2CNEsYy9cdA": Sight(
        "Musée d'Orsay", 150, Decimal("16"), source="2026 online rate, per museum ticket guides"
    ),
    "ChIJc8mX0udx5kcRWKcjTwDr5QA": Sight(
        "Panthéon", 60, Decimal("16"), source="monuments-nationaux.fr: Apr-Sep (13 Oct-Mar)"
    ),
    "ChIJOYNm1DBu5kcRZwdtKBzyq6k": Sight(
        "Palais Garnier", 75, Decimal("25"), source="operadeparis.fr: outside the EEA"
    ),
    "ChIJR3122B9u5kcRaCck3PlB9DM": Sight(
        "Sainte-Chapelle", 45, Decimal("22"), source="monuments-nationaux.fr: non-EEA since 12 Jan 2026"
    ),
    "ChIJUzCPuddv5kcRasGAnEUUWkU": Sight(
        "Hôtel des Invalides (Army Museum, Napoleon's tomb)",
        150,
        Decimal("17"),
        source="musee-armee.fr 2026 price list",
    ),
    "ChIJv-rX7Ndv5kcRJ0IdTc55HnY": Sight("Musée de l'Armée", same_as="ChIJUzCPuddv5kcRasGAnEUUWkU"),
    "ChIJ2egWXk5x5kcRZZl30h-FWtY": Sight("Napoleon's Tomb", same_as="ChIJUzCPuddv5kcRasGAnEUUWkU"),
    "ChIJdbbQwbZx5kcRs7Qu5nPw18g": Sight(
        "Catacombs of Paris", 75, Decimal("31"), source="catacombes.paris.fr: audio guide included"
    ),
    "ChIJZZTY3PBt5kcR6jdmzirZ-eY": Sight(
        "Atelier des Lumières", 75, Decimal("19.50"), source="2026 adult rate at official resellers"
    ),
    "ChIJVUrgmz5u5kcRWPSN-T8a730": Sight(
        "Musée Grévin", 90, Decimal("28"), source="2026 walk-up rate, per ticket guides"
    ),
    "ChIJo6qq6i5u5kcRCpYBp4rQP9w": Sight(
        "Musée de l'Orangerie", 60, Decimal("12.50"), source="musee-orangerie.fr ticketing (search result)"
    ),
    "ChIJQ9vMHipw5kcRWHC2ESjYaGQ": Sight("Musée Rodin", 90, Decimal("14"), source="musee-rodin.fr"),
    "ChIJSUOPztFv5kcRnEbSPYG-9fM": Sight("Petit Palais", 75, Decimal(0), source="free permanent collection"),
    "ChIJfRtS-QBu5kcRwRg5JXVrwcg": Sight("Carnavalet Museum", 75, Decimal(0), source="free permanent collection"),
    "ChIJa-wm0fBx5kcRTj1XkfsieqY": Sight("Jardin des Plantes", 60, Decimal(0), source="the garden is free"),
    "ChIJKZKprAFy5kcREOvlZ8mwHiM": Sight("Place de la Bastille", 15, Decimal(0)),
    "ChIJB0gcnCBw5kcRHoIAPcTEApc": Sight("Champ de Mars", 30),
    "ChIJoxY3R-Nv5kcRWsRDGBoNIOk": Sight("Jardins du Trocadéro", 30),
    "ChIJATr1n-Fx5kcRjQb6q6cdQDY": Sight("Notre-Dame Cathedral of Paris", 45),
    # --- Istanbul ---
    "ChIJQ3x3p-e5yhQRCzOLzD3Pdkw": Sight(
        "Galata Tower", 60, source="galatakulesi.gov.tr: 30 EUR for everyone, so no TRY price"
    ),
    "ChIJM_ilr7i5yhQRAFMBw0MZqhU": Sight(
        "Topkapı Palace",
        180,
        Decimal("450"),
        source="2026 citizen price per travel guides; Harem and Hagia Irene included",
    ),
    "ChIJyWrG4L25yhQRcYRt7uEvwGA": Sight(
        "Basilica Cistern", 45, Decimal("1"), source="İBB, reported by Hürriyet: 1 TL for citizens since 18 Apr 2026"
    ),
    "ChIJ4307Gna3yhQRC4M7zzg-09w": Sight(
        "Dolmabahçe Palace", 120, Decimal("250"), source="Milli Saraylar citizen price, Jan 2026 update (travel guide)"
    ),
    "ChIJI6JBbXe3yhQRSEetebnYay4": Sight("Dolmabahçe Clock Tower", same_as="ChIJ4307Gna3yhQRC4M7zzg-09w"),
    "ChIJDwwhAtq3yhQRCucO58KmTqo": Sight(
        "Beylerbeyi Palace", 75, Decimal("200"), source="Milli Saraylar citizen price, 2026 (news reports)"
    ),
    "ChIJQbdCWr-5yhQRKTjvSx6RF7M": Sight(
        "Istanbul Archaeological Museums", 120, Decimal("340"), source="2026 citizen price (eleman.net guide)"
    ),
    "ChIJ9WsAScqwyhQRHNfCzoxQiTE": Sight("Miniatürk", 90, Decimal("275"), source="2026 reports vary 250-275 TL"),
    "ChIJX0SZ6iu4yhQRbEe0zrr0124": Sight("Maiden's Tower", 75, source="priced in EUR plus boat, so no TRY price"),
    "ChIJJxwBkr65yhQRrk9EN29vbiM": Sight(
        "Hagia Sophia", 45, Decimal(0), source="free for citizens (the upper gallery costs extra)"
    ),
    "ChIJ4fRwZb25yhQRpHwVijb3LeU": Sight("Blue Mosque", 30),
    "ChIJn9t8b-u5yhQRXVCwl43vu0Q": Sight("Egyptian Bazaar", 45, Decimal(0)),
    "ChIJJwXXYpG5yhQRq5jBWgtoyGQ": Sight("Grand Bazaar", 90, Decimal(0)),
    "ChIJHx3DzPO3yhQRZ5g8JNHYTUg": Sight("Taksim Square", 20, Decimal(0)),
    "ChIJE5G_T4-5yhQRcRruEEvEG3I": Sight("Beyazıt Square", 15, Decimal(0)),
    "ChIJuZd_9Mi3yhQRttg5hEG81fU": Sight("Ortaköy Square", 30, Decimal(0)),
    "ChIJGfY49mC3yhQRU_-U8XuSc7o": Sight("Çiçek Pasajı", 20, Decimal(0)),
    "ChIJQy2NxfS5yhQRj9K4NfiPweQ": Sight("Eminönü Square", 20, Decimal(0)),
    "ChIJM_wBSqXJyhQRx17gdpw5I88": Sight("Çamlıca Hill", 30, Decimal(0)),
    "ChIJSbPdxJa5yhQRm7PHl1ASRfM": Sight("Column of Constantine", 10, Decimal(0)),
}

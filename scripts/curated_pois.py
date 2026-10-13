"""Must-see streets and districts, entered by hand.

Google Places returns them as unrated "neighborhood" entries or as unrelated businesses (a cafe,
a tram stop, a mall), so scripts/ingest_places.py adds them from this list, and
scripts/localize_pois.py takes their Turkish names from here.
"""

from dataclasses import dataclass

from app.models.poi import POICategory


@dataclass(frozen=True)
class CuratedPOI:
    slug: str
    name: str  # in English, or as English speakers call it
    name_tr: str  # as Turkish speakers call it
    lat: float
    lng: float
    avg_duration_min: int
    category: POICategory = POICategory.LANDMARK


CURATED_POIS: dict[str, list[CuratedPOI]] = {
    "paris": [
        CuratedPOI("champs-elysees", "Avenue des Champs-Élysées", "Şanzelize Caddesi", 48.8698, 2.3076, 60),
        CuratedPOI("montmartre", "Montmartre", "Montmartre", 48.8865, 2.3408, 120),
        CuratedPOI("le-marais", "Le Marais", "Le Marais", 48.8575, 2.3590, 120),
        CuratedPOI("canal-saint-martin", "Canal Saint-Martin", "Saint-Martin Kanalı", 48.8710, 2.3650, 60),
    ],
    "istanbul": [
        CuratedPOI("istiklal-avenue", "İstiklal Avenue", "İstiklal Caddesi", 41.0337, 28.9778, 90),
        CuratedPOI(
            "pierre-loti-hill", "Pierre Loti Hill", "Pierre Loti Tepesi", 41.0535, 28.9335, 60, POICategory.VIEWPOINT
        ),
        CuratedPOI("balat", "Balat", "Balat", 41.0296, 28.9483, 90),
    ],
}


def curated_place_id(city_id: str, slug: str) -> str:
    """The POI's place_id: not a Google ID, but stable, so upserts stay idempotent."""
    return f"curated:{city_id}:{slug}"


CURATED_NAMES_TR = {
    curated_place_id(city_id, poi.slug): poi.name_tr for city_id, pois in CURATED_POIS.items() for poi in pois
}

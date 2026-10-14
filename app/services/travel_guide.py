"""The travel guide: what each city is like month by month, and the best cities for each month.

The texts were written by hand (in Turkish, translated into English) and live in
app/data/travel_guide.json, so they change with a commit, not a database migration:

    {"cities": {"<city id>": {"country": "NL", "months": [{"tr": "...", "en": "..."}, ... 12],
                              "note": {"tr": "...", "en": "..."}}},   # note: optional, about the whole year
     "best": {"1": [{"city": "<city id>", "tr": "...", "en": "..."}, ... 5], ... "12": [...]}}
"""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

GUIDE_FILE = Path(__file__).resolve().parents[1] / "data" / "travel_guide.json"

Continent = Literal["europe", "asia", "africa", "north_america"]
CONTINENTS: tuple[Continent, ...] = ("europe", "asia", "africa", "north_america")
# By country. Turkey counts as Europe: the guide's Turkish city is Istanbul.
CONTINENT_OF_COUNTRY: dict[str, Continent] = {
    **dict.fromkeys(
        ["AT", "BA", "BE", "CH", "CZ", "DE", "DK", "ES", "FR", "GB", "GR", "HR", "HU", "IE", "IT", "NL", "NO", "PL",
         "PT", "RS", "SE", "TR"],
        "europe",
    ),
    **dict.fromkeys(["AE", "AZ", "CN", "GE", "HK", "ID", "IN", "JP", "KR", "QA", "SG", "TH", "VN"], "asia"),
    **dict.fromkeys(["EG", "MA", "TN", "ZA"], "africa"),
    **dict.fromkeys(["CA", "MX", "US"], "north_america"),
}  # fmt: skip


@dataclass(frozen=True)
class GuideCity:
    id: str
    country_code: str
    continent: Continent
    months: tuple[str, ...]  # January first
    note: str | None = None  # about the whole year, e.g. "hot and humid all year round"


@dataclass(frozen=True)
class BestPick:
    city_id: str
    text: str


@dataclass(frozen=True)
class Guide:
    cities: tuple[GuideCity, ...]
    best: tuple[tuple[BestPick, ...], ...]  # January first, five picks a month


@lru_cache
def load_guide(lang: Literal["tr", "en"]) -> Guide:
    """The guide in one language, read from the data file once per process."""
    data = json.loads(GUIDE_FILE.read_text(encoding="utf-8"))
    cities = tuple(
        GuideCity(
            id=city_id,
            country_code=entry["country"],
            continent=CONTINENT_OF_COUNTRY[entry["country"]],
            months=tuple(month[lang] for month in entry["months"]),
            note=entry["note"][lang] if "note" in entry else None,
        )
        for city_id, entry in data["cities"].items()
    )
    best = tuple(
        tuple(BestPick(city_id=pick["city"], text=pick[lang]) for pick in data["best"][str(month)])
        for month in range(1, 13)
    )
    return Guide(cities=cities, best=best)

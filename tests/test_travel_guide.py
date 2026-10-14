"""The travel guide: the hand-written data file and the endpoint that serves it (no database)."""

import json
import re

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.travel_guide import CONTINENT_OF_COUNTRY, CONTINENTS, GUIDE_FILE, load_guide
from scripts.city_catalog import CATALOG
from scripts.ingest_places import CITIES

DATA = json.loads(GUIDE_FILE.read_text(encoding="utf-8"))
KNOWN_CITIES = set(CITIES) | {c.id for c in CATALOG}
# The source files had "Ocak: ..." lines; the label must not end up in the text.
MONTH_PREFIX = re.compile(r"^(Ocak|Şubat|Mart|Nisan|Mayıs|Haziran|Temmuz|Ağustos|Eylül|Ekim|Kasım|Aralık)\s*:")


def test_every_city_has_twelve_months_in_both_languages() -> None:
    assert len(DATA["cities"]) == 32
    for city_id, entry in DATA["cities"].items():
        assert city_id in KNOWN_CITIES, city_id
        assert entry["country"] in CONTINENT_OF_COUNTRY, (city_id, entry["country"])
        assert len(entry["months"]) == 12, city_id
        for month, text in enumerate(entry["months"], start=1):
            assert text["tr"].strip() and text["en"].strip(), (city_id, month)
            assert text["tr"] != text["en"], (city_id, month)
            assert not MONTH_PREFIX.match(text["tr"]), (city_id, month)  # "Ocak: ..." was stripped
            assert text["tr"] == text["tr"].strip() and "  " not in text["tr"], (city_id, month)


def test_every_month_has_five_best_cities_from_the_guide() -> None:
    assert sorted(DATA["best"], key=int) == [str(m) for m in range(1, 13)]
    for month, picks in DATA["best"].items():
        ids = [p["city"] for p in picks]
        assert len(ids) == 5 and len(set(ids)) == 5, month
        assert set(ids) <= set(DATA["cities"]), (month, ids)
        for pick in picks:
            assert pick["tr"].strip() and pick["en"].strip() and pick["tr"] != pick["en"], (month, pick["city"])


@pytest.mark.parametrize("lang", ["tr", "en"])
def test_guide_endpoint_serves_one_language(lang: str) -> None:
    with TestClient(app) as client:
        resp = client.get(f"/api/v1/guide?lang={lang}")
    assert resp.status_code == 200
    assert "max-age" in resp.headers["cache-control"]
    body = resp.json()
    assert body["lang"] == lang
    assert body["continents"] == list(CONTINENTS)
    assert len(body["cities"]) == 32 and all(len(c["months"]) == 12 for c in body["cities"])
    assert [m["month"] for m in body["best"]] == list(range(1, 13))
    amsterdam = next(c for c in body["cities"] if c["id"] == "amsterdam")
    assert (amsterdam["country_code"], amsterdam["continent"]) == ("NL", "europe")
    assert amsterdam["months"][3] == DATA["cities"]["amsterdam"]["months"][3][lang]


def test_a_city_can_have_a_note_about_the_whole_year() -> None:
    notes = {lang: {c.id: c.note for c in load_guide(lang).cities} for lang in ("tr", "en")}
    assert notes["tr"]["singapore"].startswith("Singapur ekvatorda")
    assert notes["en"]["singapore"].startswith("Singapore lies on the equator")
    assert notes["en"]["paris"] is None


def test_continents_group_the_cities() -> None:
    by_id = {c.id: c.continent for c in load_guide("en").cities}
    assert by_id["istanbul"] == "europe"
    assert by_id["tokyo"] == by_id["dubai"] == by_id["baku"] == "asia"
    assert by_id["marrakech"] == "africa"
    assert by_id["new-york"] == "north_america"


def test_guide_endpoint_rejects_other_languages() -> None:
    with TestClient(app) as client:
        assert client.get("/api/v1/guide?lang=de").status_code == 422

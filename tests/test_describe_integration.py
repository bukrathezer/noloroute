"""Place descriptions in the database and in plans (skipped when PostgreSQL isn't reachable)."""

from collections.abc import Iterable, Sequence

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import POI
from app.services.geo import LatLng
from app.services.wikipedia import Entity
from scripts.describe_pois import describe_city, fill_sitelinks
from tests.seed import CITY_ID, HOTEL, POI_COUNT


class FakeWiki:
    """A Wikipedia that has articles about some of the test city's sights, right where they are."""

    def __init__(self, articles: dict[str, LatLng]) -> None:
        self.articles = articles

    def search(self, name: str) -> list[tuple[str, LatLng]]:
        return [(f"Q-{name}", self.articles[name])] if name in self.articles else []

    def nearby(self, where: LatLng, radius_m: int) -> dict[str, float]:
        return {}

    def entities(self, qids: Sequence[str], languages: Iterable[str]) -> dict[str, Entity]:
        names = [q.removeprefix("Q-") for q in qids]
        return {f"Q-{n}": Entity(f"Q-{n}", [n], "museum in Test City", {"tr": f"{n} TR", "en": n}, 12) for n in names}

    def intros(self, lang: str, titles: Sequence[str]) -> dict[str, str]:
        return {t: f"{t} is a sight in Test City, known for its old walls and gardens, in {lang}." for t in titles}


def sights(db: Session) -> dict[str, POI]:
    db.expire_all()
    return {p.name: p for p in db.scalars(select(POI).where(POI.city_id == CITY_ID))}


def test_describe_city_stores_descriptions_and_skips_places_already_looked_up(seeded: Session) -> None:
    known = {
        name: LatLng(p.latitude, p.longitude) for name, p in sights(seeded).items() if name in ("Sight 0", "Sight 3")
    }
    api = FakeWiki(known)

    assert describe_city(seeded, CITY_ID, api, log=lambda _: None) == (POI_COUNT, 2)
    after = sights(seeded)
    assert after["Sight 0"].wikidata_sitelinks == 12
    assert (after["Sight 0"].wikidata_id, after["Sight 0"].description_en, after["Sight 0"].description_tr) == (
        "Q-Sight 0",
        "Sight 0 is a sight in Test City, known for its old walls and gardens, in en.",
        "Sight 0 TR is a sight in Test City, known for its old walls and gardens, in tr.",
    )
    assert after["Sight 1"].wikidata_id is None and after["Sight 1"].description_en is None
    assert all(p.wiki_checked_at is not None for p in after.values())

    # A second run has nothing left to look up, unless asked to look again.
    assert describe_city(seeded, CITY_ID, api, log=lambda _: None) == (0, 0)
    assert describe_city(seeded, CITY_ID, api, again=True, log=lambda _: None) == (POI_COUNT, 2)


class CountingWiki(FakeWiki):
    def sitelink_counts(self, qids: Sequence[str]) -> dict[str, int]:
        return {qid: 40 for qid in qids}


def test_fill_sitelinks_stores_counts_for_places_matched_earlier(seeded: Session) -> None:
    for poi in sights(seeded).values():
        poi.wikidata_id = f"Q-{poi.name}"
    seeded.flush()
    assert fill_sitelinks(seeded, CountingWiki({}), CITY_ID) == POI_COUNT
    assert {p.wikidata_sitelinks for p in sights(seeded).values()} == {40}
    assert fill_sitelinks(seeded, CountingWiki({}), CITY_ID) == 0  # nothing left to fill


def test_dry_run_writes_nothing(seeded: Session) -> None:
    known = {name: LatLng(p.latitude, p.longitude) for name, p in sights(seeded).items()}
    lines: list[str] = []
    describe_city(seeded, CITY_ID, FakeWiki(known), dry_run=True, log=lines.append)
    assert len(lines) == POI_COUNT
    assert all(p.wiki_checked_at is None and p.wikidata_id is None for p in sights(seeded).values())


def test_plan_shows_the_descriptions(client: TestClient, seeded: Session) -> None:
    for poi in sights(seeded).values():
        poi.wikidata_id, poi.description_tr, poi.description_en = "Q42", "Bir yer.", "A place."
    seeded.flush()

    resp = client.post("/api/v1/routes/plan", json={"city_id": CITY_ID, "accommodation": HOTEL, "duration_days": 1})
    assert resp.status_code == 200
    stop = resp.json()["days"][0]["stops"][0]
    assert (stop["wikidata_id"], stop["description_tr"], stop["description_en"]) == ("Q42", "Bir yer.", "A place.")

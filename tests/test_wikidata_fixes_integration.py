"""Hand-checked Wikidata corrections (scripts/wikidata_overrides.py) in matching, Turkish names and
the clean-up of existing matches (skipped when PostgreSQL isn't reachable)."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import POI
from app.services.geo import LatLng
from scripts import describe_pois, fix_wikidata_matches, localize_pois
from scripts.describe_pois import describe_city
from scripts.fix_wikidata_matches import fix_matches
from scripts.localize_pois import Budget, localize_city
from tests.seed import CITY_ID
from tests.test_describe_integration import FakeWiki
from tests.test_localize_integration import FakeGoogle, FakeLabels


def pois(db: Session) -> dict[str, POI]:
    db.expire_all()
    return {p.name: p for p in db.scalars(select(POI).where(POI.city_id == CITY_ID))}


@pytest.fixture
def overrides(monkeypatch: pytest.MonkeyPatch) -> tuple[dict[str, str], dict[str, str]]:
    """Sight 0 was matched to a wrong item, Sight 1 to the larger whole it is part of."""
    wrong, part = {"test-place-0": "wrong item"}, {"test-place-1": "part of a whole"}
    for module in (describe_pois, localize_pois, fix_wikidata_matches):
        monkeypatch.setattr(module, "WRONG", wrong)
        monkeypatch.setattr(module, "PART", part)
    return wrong, part


def test_matching_skips_wrong_places_and_part_places_get_no_fame(seeded: Session, overrides) -> None:
    by_name = pois(seeded)
    articles = {n: LatLng(by_name[n].latitude, by_name[n].longitude) for n in ("Sight 0", "Sight 1", "Sight 2")}
    describe_city(seeded, CITY_ID, FakeWiki(articles), log=lambda _: None)
    after = pois(seeded)
    assert after["Sight 0"].wikidata_id is None and after["Sight 0"].description_en is None  # never looked up
    assert after["Sight 0"].wiki_checked_at is not None  # and not looked up again next time
    assert after["Sight 1"].wikidata_id == "Q-Sight 1" and after["Sight 1"].description_en  # keeps the context
    assert after["Sight 1"].wikidata_sitelinks is None  # but not the whole's fame
    assert after["Sight 2"].wikidata_sitelinks == 12  # an ordinary match


def test_turkish_names_of_part_places_come_from_google_not_the_label(seeded: Session, overrides) -> None:
    by_name = pois(seeded)
    by_name["Sight 1"].wikidata_id = "Q-whole"
    by_name["Sight 2"].wikidata_id = "Q-own"
    seeded.flush()
    localize_city(
        seeded,
        CITY_ID,
        FakeLabels({"Q-whole": "Bütünün Adı", "Q-own": "Kendi Adı"}),
        FakeGoogle(),
        None,
        Budget(name_requests=100, characters=0),
        log=lambda _: None,
    )
    after = pois(seeded)
    assert after["Sight 1"].name_tr == "Google TR test-place-1"
    assert after["Sight 2"].name_tr == "Kendi Adı"


def test_fix_matches_cleans_existing_matches_once(seeded: Session, overrides) -> None:
    by_name = pois(seeded)
    wrong, part = by_name["Sight 0"], by_name["Sight 1"]
    wrong.wikidata_id, wrong.wikidata_sitelinks, wrong.name_tr = "Q-chain", 17, "109 (alışveriş merkezi)"
    wrong.description_tr, wrong.description_en, wrong.description_translated = "Mağaza zinciri.", "A store chain.", "tr"
    part.wikidata_id, part.wikidata_sitelinks, part.name_tr = "Q-park", 63, "Hyde Park"
    part.description_en = "Hyde Park is a park."
    seeded.flush()

    cities, changed = fix_matches(seeded, dry_run=True)
    assert cities == {CITY_ID} and len(changed) == 2
    assert pois(seeded)["Sight 0"].wikidata_id == "Q-chain"  # a dry run writes nothing

    fix_matches(seeded)
    after = pois(seeded)
    w, p = after["Sight 0"], after["Sight 1"]
    assert (w.wikidata_id, w.wikidata_sitelinks, w.name_tr) == (None, None, None)
    assert (w.description_tr, w.description_en, w.description_translated) == (None, None, None)
    assert (p.wikidata_id, p.description_en) == ("Q-park", "Hyde Park is a park.")  # the context stays
    assert (p.wikidata_sitelinks, p.name_tr) == (None, None)

    # Once the names are filled again, a second run leaves them alone.
    p.name_tr = "Hyde Park Gül Bahçesi"
    seeded.flush()
    assert fix_matches(seeded) == (set(), set())
    assert pois(seeded)["Sight 1"].name_tr == "Hyde Park Gül Bahçesi"


def test_the_override_lists_are_consistent() -> None:
    from scripts.wikidata_overrides import PART, WRONG

    assert len(WRONG) == 61 and len(PART) == 132  # the October 2026 audit
    assert not WRONG.keys() & PART.keys()
    assert all(key.startswith("ChIJ") for key in [*WRONG, *PART])  # Google place ids
    assert all(" -> " in note for note in [*WRONG.values(), *PART.values()])

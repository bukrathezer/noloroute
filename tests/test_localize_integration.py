"""Turkish names and translated descriptions in the database, in plans and in saved routes
(skipped when PostgreSQL isn't reachable)."""

from collections.abc import Sequence

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import POI
from app.services.geo import LatLng
from app.services.places_client import PlacesAPIError
from app.services.translate import TranslateError
from scripts.describe_pois import describe_city
from scripts.localize_pois import Budget, localize_city
from tests.seed import CITY_ID, HOTEL, POI_COUNT
from tests.test_describe_integration import FakeWiki

PASSWORD = "s3cure-enough-password"


class FakeLabels:
    def __init__(self, labels: dict[str, str]) -> None:
        self.labels_by_qid = labels
        self.asked: list[str] = []

    def labels(self, qids: Sequence[str], lang: str) -> dict[str, str]:
        assert lang == "tr"
        self.asked += qids
        return {q: self.labels_by_qid[q] for q in qids if q in self.labels_by_qid}


class FakeGoogle:
    def __init__(self, fail: dict[str, int] | None = None, local: set[str] | None = None) -> None:
        self.fail = fail or {}  # place_id -> HTTP status
        self.local = local or set()  # places Google has no Turkish name for: it answers in Japanese
        self.asked: list[str] = []

    def display_name(self, place_id: str, language: str) -> tuple[str, str | None] | None:
        assert language == "tr"
        self.asked.append(place_id)
        if place_id in self.fail:
            raise PlacesAPIError(self.fail[place_id], "nope")
        if place_id in self.local:
            return ("清水寺", "ja")
        return (f"Google TR {place_id}", "tr")


class FakeTranslator:
    def __init__(self, fail: bool = False, grow: int = 0) -> None:
        self.fail = fail
        self.grow = grow  # characters to add, to test fitting into the column
        self.calls: list[tuple[str, str, list[str]]] = []

    def translate(self, texts: Sequence[str], source: str, target: str) -> list[str]:
        if self.fail:
            raise TranslateError("Translation API error 403: not enabled")
        self.calls.append((source, target, list(texts)))
        return [f"[{target}] {t}" + " uzun" * self.grow for t in texts]


def pois(db: Session) -> dict[str, POI]:
    db.expire_all()
    return {p.name: p for p in db.scalars(select(POI).where(POI.city_id == CITY_ID))}


def run(db: Session, wiki=None, google=None, translator=None, budget: Budget | None = None, **kw):
    return localize_city(
        db,
        CITY_ID,
        wiki or FakeLabels({}),
        google,
        translator,
        budget or Budget(name_requests=100, characters=100_000),
        log=lambda _: None,
        **kw,
    )


# --- names ------------------------------------------------------------------------------------------


def test_names_come_from_wikidata_first_then_google(seeded: Session) -> None:
    by_name = pois(seeded)
    by_name["Sight 0"].wikidata_id = "Q0"
    by_name["Sight 1"].wikidata_id = "Q1"  # Wikidata has no Turkish label for it
    seeded.flush()
    wiki, google = FakeLabels({"Q0": "sekizinci yer"}), FakeGoogle()

    report = run(seeded, wiki, google)
    after = pois(seeded)
    assert after["Sight 0"].name_tr == "Sekizinci yer"  # tidied
    assert after["Sight 1"].name_tr == "Google TR test-place-1"
    assert all(p.name_tr for p in after.values())
    assert (report.names_from_wikidata, report.names_from_google, report.names_left) == (1, POI_COUNT - 1, 0)
    assert "test-place-0" not in google.asked

    # Everything is stored: a second run asks nobody.
    wiki2, google2 = FakeLabels({"Q0": "x"}), FakeGoogle()
    run(seeded, wiki2, google2)
    assert wiki2.asked == [] and google2.asked == []


def test_name_requests_stop_at_the_budget_most_popular_first(seeded: Session) -> None:
    google = FakeGoogle()
    budget = Budget(name_requests=3, characters=0)
    report = run(seeded, google=google, budget=budget)
    # Seed popularity grows with the number: Sight 11 is the most reviewed.
    assert google.asked == ["test-place-11", "test-place-10", "test-place-9"]
    assert (report.names_from_google, report.names_left, budget.name_requests) == (3, POI_COUNT - 3, 0)
    assert pois(seeded)["Sight 8"].name_tr is None  # waits for the next run


def test_top_keeps_google_names_to_the_most_popular_places(seeded: Session) -> None:
    google = FakeGoogle()
    report = run(seeded, google=google, budget=Budget(name_requests=100, characters=0, top=2))
    assert google.asked == ["test-place-11", "test-place-10"]
    assert report.names_skipped == POI_COUNT - 2


def test_a_second_listing_of_an_item_gets_its_own_google_name(seeded: Session) -> None:
    by_name = pois(seeded)
    by_name["Sight 11"].wikidata_id = "Q-palace"  # the most reviewed: the item itself
    by_name["Sight 2"].wikidata_id = "Q-palace"  # a part of it, listed separately
    seeded.flush()
    run(seeded, FakeLabels({"Q-palace": "Topkapı Sarayı"}), FakeGoogle())
    after = pois(seeded)
    assert after["Sight 11"].name_tr == "Topkapı Sarayı"
    assert after["Sight 2"].name_tr == "Google TR test-place-2"


def test_a_google_answer_in_another_language_isnt_taken_for_turkish(seeded: Session) -> None:
    by_name = pois(seeded)
    by_name["Sight 1"].wikidata_id = "Q1"
    by_name["Sight 1"].place_id = "temple-with-label"
    by_name["Sight 2"].place_id = "temple-without"
    seeded.flush()
    second = pois(seeded)
    # Sight 1's item has no Turkish label either way, so Google is asked about both.
    run(seeded, FakeLabels({}), FakeGoogle(local={"temple-with-label", "temple-without"}))
    after = pois(seeded)
    assert after["Sight 1"].name_tr == "Sight 1"  # its own (English) name, not Japanese
    assert after["Sight 2"].name_tr == "Sight 2"  # stored, so it isn't paid for again
    assert second


def test_a_refusing_google_isnt_asked_again_that_run(seeded: Session) -> None:
    google = FakeGoogle(fail={"test-place-11": 403})
    report = run(seeded, google=google)
    assert google.asked == ["test-place-11"]
    assert report.names_left == POI_COUNT


def test_failed_google_answers_are_tried_again_except_missing_places(seeded: Session) -> None:
    google = FakeGoogle(fail={"test-place-11": 500, "test-place-10": 404})
    report = run(seeded, google=google)
    after = pois(seeded)
    assert after["Sight 11"].name_tr is None  # next run tries again
    assert after["Sight 10"].name_tr == "Sight 10"  # gone from Google: keeps its name
    assert report.names_left == 1


def test_hand_added_places_keep_their_name_or_take_the_wikidata_label(seeded: Session) -> None:
    by_name = pois(seeded)
    by_name["Sight 0"].place_id = "curated:test:old-town"
    by_name["Sight 1"].place_id = "curated:test:avenue"
    by_name["Sight 1"].wikidata_id = "Q-avenue"
    seeded.flush()
    google = FakeGoogle()
    run(seeded, FakeLabels({"Q-avenue": "İstiklal Caddesi"}), google)
    after = pois(seeded)
    assert after["Sight 0"].name_tr == "Sight 0"
    assert after["Sight 1"].name_tr == "İstiklal Caddesi"
    assert not any(p.startswith("curated:") for p in google.asked)


def test_without_google_only_wikidata_names_are_filled(seeded: Session) -> None:
    pois(seeded)["Sight 0"].wikidata_id = "Q0"
    seeded.flush()
    report = run(seeded, FakeLabels({"Q0": "Sıfırıncı Yer"}), google=None)
    assert pois(seeded)["Sight 0"].name_tr == "Sıfırıncı Yer"
    assert report.names_left == POI_COUNT - 1


# --- descriptions -------------------------------------------------------------------------------------


def describe(db: Session, **texts: tuple[str | None, str | None]) -> None:
    by_name = pois(db)
    for name, (tr, en) in texts.items():
        poi = by_name[name.replace("_", " ")]
        poi.wikidata_id, poi.description_tr, poi.description_en = f"Q-{poi.name}", tr, en
    db.flush()


def test_a_description_in_one_language_is_translated_into_the_other(seeded: Session) -> None:
    describe(
        seeded,
        Sight_0=(None, "An old gate."),
        Sight_1=("Eski bir köprü.", None),
        Sight_2=("İki dilde.", "In both."),
    )
    translator = FakeTranslator()
    report = run(seeded, translator=translator)
    after = pois(seeded)
    assert (after["Sight 0"].description_tr, after["Sight 0"].description_translated) == ("[tr] An old gate.", "tr")
    assert (after["Sight 1"].description_en, after["Sight 1"].description_translated) == ("[en] Eski bir köprü.", "en")
    assert after["Sight 2"].description_translated is None  # both from Wikipedia: untouched
    assert sorted((s, t) for s, t, _ in translator.calls) == [("en", "tr"), ("tr", "en")]
    assert report.translated == 2
    assert report.characters == len("An old gate.") + len("Eski bir köprü.")

    again = FakeTranslator()
    run(seeded, translator=again)
    assert again.calls == []  # translated once, stored for good


def test_translations_stop_at_the_character_budget(seeded: Session) -> None:
    describe(seeded, Sight_11=(None, "a" * 40), Sight_10=(None, "b" * 40))
    budget = Budget(name_requests=0, characters=50)
    report = run(seeded, translator=FakeTranslator(), budget=budget)
    after = pois(seeded)
    assert after["Sight 11"].description_tr is not None  # the more popular one first
    assert after["Sight 10"].description_tr is None
    assert (report.translated, report.translations_left, budget.characters) == (1, 1, 10)


def test_long_translations_fit_the_column(seeded: Session) -> None:
    describe(seeded, Sight_0=(None, "A gate. " * 30))
    run(seeded, translator=FakeTranslator(grow=80))
    text = pois(seeded)["Sight 0"].description_tr
    assert len(text) <= 300 and text.endswith("…")


def test_a_failing_translation_leaves_the_descriptions_for_the_next_run(seeded: Session) -> None:
    describe(seeded, Sight_0=(None, "An old gate."))
    report = run(seeded, translator=FakeTranslator(fail=True))
    assert pois(seeded)["Sight 0"].description_tr is None
    assert report.translations_left == 1


def test_dry_run_counts_and_writes_nothing(seeded: Session) -> None:
    pois(seeded)["Sight 0"].wikidata_id = "Q0"
    seeded.flush()
    describe(seeded, Sight_1=(None, "An old gate."))
    google, translator = FakeGoogle(), FakeTranslator()
    report = run(seeded, FakeLabels({"Q0": "Yer"}), google, translator, dry_run=True)
    assert google.asked == [] and translator.calls == []
    assert all(p.name_tr is None and p.description_translated is None for p in pois(seeded).values())
    assert report.names_from_wikidata == 1 and report.names_left == POI_COUNT - 1
    assert report.characters_needed == len("An old gate.") and report.translations_left == 1


def test_describing_again_replaces_translations_and_names_of_a_new_match(seeded: Session) -> None:
    by_name = pois(seeded)
    for poi in by_name.values():
        poi.wiki_checked_at = None
    by_name["Sight 0"].wikidata_id = "Q-old"
    by_name["Sight 0"].name_tr = "Eski eşleşmenin adı"
    by_name["Sight 0"].description_translated = "tr"
    seeded.flush()
    here = {"Sight 0": by_name["Sight 0"]}
    describe_city(
        seeded, CITY_ID, FakeWiki({n: LatLng(p.latitude, p.longitude) for n, p in here.items()}), log=lambda _: None
    )
    after = pois(seeded)["Sight 0"]
    assert after.wikidata_id == "Q-Sight 0"
    assert after.name_tr is None  # looked up again for the new item
    assert after.description_translated is None  # both texts now come from Wikipedia


# --- plans and saved routes -------------------------------------------------------------------------


def plan(client: TestClient) -> dict:
    body = {"city_id": CITY_ID, "accommodation": HOTEL, "duration_days": 2}
    resp = client.post("/api/v1/routes/plan", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_plans_carry_both_names_and_the_translation_mark(client: TestClient, seeded: Session) -> None:
    describe(seeded, Sight_0=(None, "An old gate."))
    run(seeded, google=FakeGoogle(), translator=FakeTranslator())
    stops = {s["poi_id"]: s for d in plan(client)["days"] for s in d["stops"]}
    by_id = {p.id: p for p in pois(seeded).values()}
    for poi_id, stop in stops.items():
        assert stop["name"] == by_id[poi_id].name
        assert stop["name_tr"] == by_id[poi_id].name_tr
    gate = by_id[next(p.id for p in by_id.values() if p.name == "Sight 0")]
    if gate.id in stops:
        assert stops[gate.id]["description_translated"] == "tr"


def test_a_route_saved_before_turkish_names_shows_them_when_opened(client: TestClient, seeded: Session) -> None:
    old = plan(client)  # no Turkish names yet
    assert all(s["name_tr"] is None for d in old["days"] for s in d["stops"])
    old["days"][0]["dropped_stops"] = ["Sight 5"]
    old["days"][0]["dropped_stops_tr"] = []  # what a plan from before looks like

    token = client.post("/api/v1/auth/register", json={"email": "ada@example.com", "password": PASSWORD})
    headers = {"Authorization": f"Bearer {token.json()['access_token']}"}
    saved = client.post("/api/v1/routes", json={"plan": old}, headers=headers).json()

    run(seeded, google=FakeGoogle())
    reopened = client.get(f"/api/v1/routes/{saved['id']}", headers=headers).json()["plan"]
    by_id = {p.id: p for p in pois(seeded).values()}
    for day in reopened["days"]:
        for stop in day["stops"]:
            assert stop["name_tr"] == by_id[stop["poi_id"]].name_tr
    assert reopened["days"][0]["dropped_stops_tr"] == ["Google TR test-place-5"]
    # The route itself is as saved.
    assert [[s["poi_id"] for s in d["stops"]] for d in reopened["days"]] == [
        [s["poi_id"] for s in d["stops"]] for d in old["days"]
    ]


def test_removing_a_stop_keeps_turkish_names_of_dropped_stops(client: TestClient, seeded: Session) -> None:
    run(seeded, google=FakeGoogle())
    result = plan(client)
    result["days"][0]["dropped_stops"] = ["Sight 5"]
    result["days"][0]["dropped_stops_tr"] = ["Beşinci Yer"]
    removed = result["days"][0]["stops"][0]["poi_id"]
    edited = client.post("/api/v1/routes/plan/remove-stop", json={"plan": result, "poi_id": removed}).json()
    day = edited["days"][0]
    assert day["dropped_stops"][:1] == ["Sight 5"] and day["dropped_stops_tr"][:1] == ["Beşinci Yer"]
    assert len(day["dropped_stops_tr"]) == len(day["dropped_stops"])


def test_a_failed_translation_stops_translating_for_the_run(seeded: Session) -> None:
    describe(seeded, Sight_0=(None, "An old gate."), Sight_1=("Eski bir köprü.", None))
    budget = Budget(name_requests=0, characters=1_000)
    report = run(seeded, translator=FakeTranslator(fail=True), budget=budget)
    assert report.characters == 0 and report.translations_left == 2
    assert budget.characters == 0  # the next cities don't try either


def test_describing_again_keeps_a_translation_whose_source_is_unchanged(seeded: Session) -> None:
    by_name = pois(seeded)
    for poi in by_name.values():
        poi.wiki_checked_at = None
    gate = by_name["Sight 0"]
    english = "Sight 0 is a sight in Test City, known for its old walls and gardens, in en."
    gate.wikidata_id, gate.description_en = "Q-Sight 0", english
    gate.description_tr, gate.description_translated = "Çevrilmiş metin.", "tr"
    seeded.flush()

    class EnglishOnly(FakeWiki):  # Wikipedia still has no Turkish article
        def entities(self, qids, languages):
            found = super().entities(qids, languages)
            for entity in found.values():
                entity.articles.pop("tr")
            return found

    describe_city(seeded, CITY_ID, EnglishOnly({"Sight 0": LatLng(gate.latitude, gate.longitude)}), log=lambda _: None)
    after = pois(seeded)["Sight 0"]
    assert (after.description_en, after.description_tr, after.description_translated) == (
        english,
        "Çevrilmiş metin.",
        "tr",
    )


def test_a_saved_route_keeps_its_turkish_dropped_names_and_skips_ambiguous_ones(
    client: TestClient, seeded: Session
) -> None:
    by_name = pois(seeded)
    by_name["Sight 6"].name = "Twin Mosque"  # two places of the city share an English name
    by_name["Sight 7"].name = "Twin Mosque"
    by_name["Sight 6"].name_tr, by_name["Sight 7"].name_tr = "Birinci Cami", "İkinci Cami"
    seeded.flush()
    result = plan(client)
    result["days"][0]["dropped_stops"], result["days"][0]["dropped_stops_tr"] = ["Sight 5"], ["Saklanan Ad"]
    result["days"][1]["dropped_stops"], result["days"][1]["dropped_stops_tr"] = ["Twin Mosque"], []

    token = client.post("/api/v1/auth/register", json={"email": "ada@example.com", "password": PASSWORD})
    headers = {"Authorization": f"Bearer {token.json()['access_token']}"}
    saved = client.post("/api/v1/routes", json={"plan": result}, headers=headers).json()
    days = client.get(f"/api/v1/routes/{saved['id']}", headers=headers).json()["plan"]["days"]
    assert days[0]["dropped_stops_tr"] == ["Saklanan Ad"]  # stored with the plan: kept
    assert days[1]["dropped_stops_tr"] == ["Twin Mosque"]  # which of the two? English rather than a guess

"""Matching places to Wikipedia and shortening the articles' introductions (no network)."""

import json
from collections.abc import Iterable, Sequence

import httpx
import pytest

from app.services.geo import LatLng
from app.services.wikipedia import (
    MATCH_THRESHOLD,
    Entity,
    WikiClient,
    WikiError,
    describe,
    describes_area,
    head_kind,
    is_sight_class,
    match_place,
    name_score,
    shorten,
)


@pytest.mark.parametrize(
    ("place", "candidate", "description"),
    [
        ("Galata Tower", "Galata Tower", "tower in Istanbul"),
        ("Saint Peter’s Basilica", "St. Peter's Basilica", ""),
        ("Louvre Museum", "Louvre", "art museum in Paris, France"),
        ("Hagia Sophia Grand Mosque", "Hagia Sophia", "mosque and former church in Istanbul, Turkey"),
        ("Nidec Kyoto Tower", "Kyoto Tower", "observation tower in Kyoto, Japan"),
        ("Sanjūsangendō Temple", "Sanjūsangen-dō", "Buddhist temple in Kyoto, Japan"),
        ("Topkapi Palace Museum", "Topkapı Palace", "palace in Istanbul, Turkey"),
        ("Basilica Cistern", "Basilica Cistern", "ancient cistern in Istanbul"),  # only kind words
        ("Parc des Buttes-Chaumont", "Parc des Buttes Chaumont", "public park in Paris"),
    ],
)
def test_names_that_match(place: str, candidate: str, description: str) -> None:
    assert name_score(place, candidate, description) >= MATCH_THRESHOLD


@pytest.mark.parametrize(
    ("place", "candidate", "description"),
    [
        # A neighbourhood is not the tower or the park named after it.
        ("Galata Tower", "Galata", "neighbourhood in Beyoğlu, Istanbul"),
        ("Emirgan Park", "Emirgan", "mahalle in Sarıyer, Istanbul"),
        # The garden is not the palace in it.
        ("Jardin du Luxembourg", "Luxembourg Palace", "palace in Paris"),
        ("Beyazit Square", "Beyazıt Tower", "fire watch tower in Istanbul"),
        ("Kurumazaki Shrine", "Kurumazaki-Jinja Station", "railway station in Kyoto"),
        ("La Villette", "Grande halle de la Villette", "exhibition hall in Paris"),
        ("Fenerbahce Mosque", "Fenerbahçe", "Wikimedia disambiguation page"),
        # Something else of the same name: a mosque by the shore, a fountain in the park, a cemetery.
        ("Bebek Coast", "Bebek Camii", "mosque in Istanbul"),
        ("İBB Kadıköy Yoğurtçu Parkı", "Yoğurtçu Parkı Çeşmesi", "fountain in Istanbul"),
        ("Zippline Nakkaştepe", "Nakkaştepe Mezarlığı", "cemetery in Istanbul"),
        # The person buried there, and the statue standing on the forecourt.
        ("Tomb of Jim Morrison", "Jim Morrison", "American singer-songwriter and poet"),
        ("Parvis de la Défense", "La Défense de Paris", "bronze statue by Louis-Ernest Barrias"),
        # The gardens along the avenue, and at the foot of the tower.
        ("Jardins de l'avenue Foch", "Avenue Foch", "avenue in Paris"),
        ("Jardin de la Tour Eiffel", "Eiffel Tower", "lattice tower on the Champ de Mars"),
        # A cistern in a park, a market by a square, a tram stop named after a mosque.
        ("Gülhane Park Cistern", "Gülhane Parkı", "park in Istanbul"),
        ("Uskudar Fishermen's Market", "Üsküdar Meydanı", "square in Istanbul"),
        ("Mescid-i Selam", "Mescid-i Selam", "tram stop in İstanbul, Turkey"),
        # Nearly the same letters, a different word.
        ("Walls of Constantinople", "Fall of Constantinople", "1453 capture of the Byzantine capital"),
    ],
)
def test_names_that_do_not_match(place: str, candidate: str, description: str) -> None:
    assert name_score(place, candidate, description) < MATCH_THRESHOLD


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("Jardin de la Tour Eiffel", "garden"),
        ("Square of Saint-Jacques Tower", "square"),
        ("Musée d'Orsay", "museum"),
        ("Topkapı Palace Museum", "museum"),
        ("Yoğurtçu Parkı Çeşmesi", "fountain"),
        ("Kadıköy Moda Sahil Parkı ve Yürüyüş Yolu", "park"),
        ("Hôtel des Invalides", None),
    ],
)
def test_head_kind(name: str, kind: str | None) -> None:
    assert head_kind(name) == kind


@pytest.mark.parametrize(
    ("place", "category", "candidate", "description"),
    [
        # A name that doesn't say what the place is: its category does.
        ("La Madeleine", "RELIGIOUS_SITE", "Boulevard de la Madeleine", "boulevard in Paris"),
        ("La Villette", "PARK", "Bassin de la Villette", "canal in Paris"),
    ],
)
def test_the_category_rules_out_other_kinds_of_place(
    place: str, category: str, candidate: str, description: str
) -> None:
    assert name_score(place, candidate, description) >= MATCH_THRESHOLD  # the names alone agree
    assert name_score(place, candidate, description, category) == 0


def test_the_exact_kind_of_place_beats_a_related_one() -> None:
    museum = name_score("Musée du Luxembourg", "Musée du Luxembourg", "art museum in Paris", "MUSEUM")
    palace = name_score("Musée du Luxembourg", "Luxembourg Palace", "palace in Paris", "MUSEUM")
    assert museum > palace >= MATCH_THRESHOLD


@pytest.mark.parametrize(
    ("description", "area"),
    [
        ("mahalle (administrative quarter) in Beşiktaş, İstanbul", True),
        ("historic district of Paris, France", True),
        ("capital and largest city of France", True),
        # Saying where a place is doesn't make it an area.
        ("square in the 8th arrondissement of Paris", False),
        ("Roman Catholic church in the 1st arrondissement of Paris", False),
        ("city park in Istanbul", False),
    ],
)
def test_area_descriptions(description: str, area: bool) -> None:
    assert describes_area(description) is area


def test_shorten_drops_parentheses_and_keeps_one_long_sentence() -> None:
    intro = (
        "The Basilica Cistern (Greek: Βασιλική Κινστέρνα (Basiliké Kinstérna)), is the largest of several hundred "
        "ancient cisterns that lie beneath the city of Istanbul, Turkey. The cistern was built in the 6th century."
    )
    assert shorten(intro, "en") == (
        "The Basilica Cistern, is the largest of several hundred ancient cisterns that lie beneath the city of "
        "Istanbul, Turkey."
    )


def test_shorten_adds_a_second_sentence_to_a_short_first_one() -> None:
    intro = (
        "Louvre Müzesi, dünyanın en büyük sanat müzesidir. Fransa'nın başkenti Paris'te, Louvre Sarayı'na kurulmuştur."
    )
    assert shorten(intro, "tr") == intro


def test_shorten_does_not_end_a_sentence_after_a_roman_numeral() -> None:
    intro = (
        "Sainte-Chapelle, Fransız Kralı IX. Louis tarafından 1241-1248 yılları arasında inşa ettirilen kraliyet "
        "şapelidir. Gotik mimarinin örneğidir."
    )
    assert shorten(intro, "tr").startswith("Sainte-Chapelle, Fransız Kralı IX. Louis tarafından")


def test_shorten_cuts_a_very_long_sentence_at_a_word() -> None:
    text = shorten("Word " * 100, "en")
    assert text is not None and text.endswith("…") and len(text) <= 220


def test_shorten_skips_disambiguation_pages() -> None:
    assert shorten("Fenerbahçe may refer to: a neighbourhood, a football club, a sports club.", "en") is None


def test_shorten_skips_texts_that_say_nothing() -> None:
    assert shorten("Kadırga Park is a park in Istanbul, Turkey.", "en") is None


class FakeApi:
    """Canned answers: an article found by name, and Wikidata items around the place."""

    def __init__(self, found: list[tuple[str, LatLng]], near: dict[str, float], entities: dict[str, Entity]):
        self.found, self.near, self.items = found, near, entities
        self.intro_calls: list[tuple[str, list[str]]] = []

    def search(self, name: str) -> list[tuple[str, LatLng]]:
        return self.found

    def nearby(self, where: LatLng, radius_m: int) -> dict[str, float]:
        return self.near

    def entities(self, qids: Sequence[str], languages: Iterable[str]) -> dict[str, Entity]:
        return {q: self.items[q] for q in qids if q in self.items}

    def intros(self, lang: str, titles: Sequence[str]) -> dict[str, str]:
        self.intro_calls.append((lang, list(titles)))
        return {title: f"{title} is a quarter on the north shore of the Golden Horn." for title in titles}


GALATA = LatLng(41.0256, 28.9742)
DISTRICT = Entity("Q1", ["Galata"], "neighbourhood in Beyoğlu, Istanbul", {"en": "Galata", "tr": "Galata"}, 40)
TOWER = Entity("Q2", ["Galata Tower", "Galata Kulesi"], "tower in Istanbul", {"en": "Galata Tower"}, 50)


def test_match_falls_back_to_nearby_items_when_the_search_finds_the_wrong_place() -> None:
    api = FakeApi(found=[("Q1", GALATA)], near={"Q1": 300.0, "Q2": 7.0}, entities={"Q1": DISTRICT, "Q2": TOWER})
    match = match_place(api, "Galata Tower", GALATA, "LANDMARK", "tr")
    assert match is not None and (match.qid, match.via) == ("Q2", "nearby")


def test_match_ignores_articles_too_far_away() -> None:
    far = LatLng(GALATA.lat + 0.05, GALATA.lng)  # about 5.5 km
    api = FakeApi(found=[("Q2", far)], near={}, entities={"Q2": TOWER})
    assert match_place(api, "Galata Tower", GALATA, "LANDMARK", "tr") is None


def test_the_place_right_there_beats_a_more_famous_namesake_further_away() -> None:
    church_here = Entity("Q10", ["Saint-Pierre"], "church in Paris", {"en": "Saint-Pierre (Montmartre)"}, 10)
    church_there = Entity("Q11", ["Saint-Pierre"], "church in Paris", {"en": "Saint-Pierre (Montrouge)"}, 40)
    there = LatLng(GALATA.lat + 0.0045, GALATA.lng)  # 500 m
    api = FakeApi(found=[("Q11", there)], near={"Q10": 20.0}, entities={"Q10": church_here, "Q11": church_there})
    match = match_place(api, "Saint-Pierre", GALATA, "RELIGIOUS_SITE", "fr")
    assert match is not None and (match.qid, match.via) == ("Q10", "nearby")


def test_districts_only_match_places_that_are_districts() -> None:
    api = FakeApi(found=[("Q1", GALATA)], near={}, entities={"Q1": DISTRICT})
    assert match_place(api, "Galata", GALATA, "LANDMARK", "tr") is None
    match = match_place(api, "Galata", GALATA, "LANDMARK", "tr", is_area=True)
    assert match is not None and match.qid == "Q1"


def test_describe_fetches_each_language_from_its_own_article() -> None:
    api = FakeApi(found=[], near={}, entities={})
    match = match_place(FakeApi([("Q1", GALATA)], {}, {"Q1": DISTRICT}), "Galata", GALATA, "OTHER", "tr", True)
    assert match is not None
    texts = describe(api, [match])
    text = "Galata is a quarter on the north shore of the Golden Horn."
    assert texts == {"Q1": {"tr": text, "en": text}}
    assert api.intro_calls == [("tr", ["Galata"]), ("en", ["Galata"])]


def test_client_reads_the_api_answers() -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        if params.get("generator") == "search":

            def page(title: str, rank: int, qid: str, *coords: float) -> dict:
                found = {"title": title, "index": rank, "pageprops": {"wikibase_item": qid}}
                return {**found, "coordinates": [{"lat": coords[0], "lon": coords[1]}]} if coords else found

            pages = [
                page("Galata", 2, "Q1", 41.0, 28.9),
                page("Galata Tower", 1, "Q2", 41.0256, 28.9741),
                page("Galata (film)", 3, "Q3"),  # no coordinates: not a place
            ]
            return httpx.Response(200, json={"query": {"pages": pages}})
        if params.get("action") == "wbgetentities":
            item = {
                "labels": {"en": {"value": "Galata Tower"}, "tr": {"value": "Galata Kulesi"}},
                "aliases": {"en": [{"value": "Christea Turris"}]},
                "descriptions": {"en": {"value": "tower in Istanbul"}},
                "sitelinks": {"enwiki": {"title": "Galata Tower"}, "trwiki": {"title": "Galata Kulesi"}, "dewiki": {}},
            }
            return httpx.Response(200, json={"entities": {"Q2": item}})
        if params.get("prop") == "extracts":
            query = {
                "normalized": [{"from": "Galata_Kulesi", "to": "Galata Kulesi"}],
                "pages": [{"title": "Galata Kulesi", "extract": "Galata Kulesi, bir kuledir."}],
            }
            return httpx.Response(200, json={"query": query})
        return httpx.Response(404)

    with WikiClient(transport=httpx.MockTransport(answer), pause_s=0) as api:
        assert [qid for qid, _ in api.search("Galata Tower")] == ["Q2", "Q1"]  # by rank, with coordinates only
        tower = api.entities(["Q2"], ["en", "tr"])["Q2"]
        assert tower.names == ["Galata Tower", "Galata Kulesi", "Christea Turris"]
        assert (tower.description, tower.sitelink_count) == ("tower in Istanbul", 3)
        assert tower.articles == {"tr": "Galata Kulesi", "en": "Galata Tower"}
        assert api.intros("tr", ["Galata_Kulesi"]) == {"Galata_Kulesi": "Galata Kulesi, bir kuledir."}


@pytest.mark.parametrize(
    ("classes", "sight"),
    [
        ("arch bridge|stone bridge", True),
        ("forest|urban park", True),
        ("minor basilica|Catholic cathedral", True),
        ("statue", True),  # an outdoor statue, like the Little Mermaid
        # A work of art in a museum, an official residence, a building that is gone, a school.
        ("statue|archaeological artefact", False),
        ("official residence|city palace", False),
        ("palace|destroyed building or structure", False),
        ("museum|art academy|university", False),
        ("treaty", False),
    ],
)
def test_sight_classes(classes: str, sight: bool) -> None:
    assert is_sight_class(classes) is sight


def test_client_reads_famous_places_from_wikidatas_query_service() -> None:
    def row(qid: str, label: str, links: int, point: str, classes: str) -> dict:
        return {
            "item": {"value": f"http://www.wikidata.org/entity/{qid}"},
            "label": {"value": label},
            "links": {"value": str(links)},
            "coord": {"value": point},
            "classes": {"value": classes},
        }

    rows = [
        row("Q6373", "British Museum", 130, "Point(-0.126944444 51.519444444)", "national museum|art museum"),
        row("Q795691", "King's Cross station", 60, "Point(-0.1236 51.5309)", "railway station"),
        row("Q6373", "British Museum", 130, "Point(-0.127 51.519)", "national museum"),  # a second coordinate
    ]
    sent = []

    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={"results": {"bindings": rows}})

    with WikiClient(transport=httpx.MockTransport(answer), pause_s=0) as api:
        places = api.famous_places(LatLng(51.5074, -0.1278), 12.0)
    assert [(p.qid, p.label, p.sitelink_count) for p in places] == [("Q6373", "British Museum", 130)]
    assert (round(places[0].where.lat, 3), round(places[0].where.lng, 3)) == (51.519, -0.127)
    assert "formatversion" not in sent[0].url.params  # the SPARQL endpoint doesn't take it


def test_client_skips_articles_that_redirect_elsewhere() -> None:
    grave = {
        "labels": {"en": {"value": "grave of Jim Morrison"}},
        "descriptions": {"en": {"value": "tomb at Père-Lachaise cemetery in Paris"}},
        # "Grave of Jim Morrison" is a redirect to the singer's article.
        "sitelinks": {"enwiki": {"title": "Grave of Jim Morrison", "badges": ["Q70893996"]}},
    }
    answer = httpx.MockTransport(lambda _: httpx.Response(200, json={"entities": {"Q24265482": grave}}))
    with WikiClient(transport=answer, pause_s=0) as api:
        assert api.entities(["Q24265482"], ["en"])["Q24265482"].articles == {}


def test_client_retries_when_throttled() -> None:
    calls = []

    def answer(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, content=json.dumps({"query": {"geosearch": [{"title": "Q2", "dist": 7.0}]}}))

    with WikiClient(transport=httpx.MockTransport(answer), pause_s=0, retry_wait_s=0) as api:
        assert api.nearby(GALATA, 600) == {"Q2": 7.0}
    assert len(calls) == 2


def test_client_retries_when_the_search_is_busy() -> None:
    answers = iter(
        [
            {
                "error": {
                    "code": "search-backend-error",
                    "info": "Search is currently too busy. Please try again later.",
                }
            },
            {"query": {"geosearch": []}},
        ]
    )

    with WikiClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=next(answers))), pause_s=0, retry_wait_s=0
    ) as api:
        assert api.nearby(GALATA, 600) == {}


def test_client_gives_up_on_other_errors() -> None:
    error = {"error": {"code": "badvalue", "info": "Unrecognized value for parameter."}}
    with (
        WikiClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=error)), pause_s=0) as api,
        pytest.raises(WikiError, match="Unrecognized value"),
    ):
        api.nearby(GALATA, 600)

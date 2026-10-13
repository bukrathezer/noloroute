"""Turkish names and translated descriptions: the clients and the helpers (no database)."""

import json
from types import SimpleNamespace

import httpx
import pytest

from app.services.places_client import PlacesAPIError, PlacesClient
from app.services.translate import TranslateClient, TranslateError
from app.services.wikipedia import WikiClient
from scripts.localize_pois import fit, second_listings, tidy_label


def test_tidy_label_capitalizes_like_turkish() -> None:
    assert tidy_label("place de la Concorde") == "Place de la Concorde"
    assert tidy_label("istiklal Caddesi") == "İstiklal Caddesi"  # dotted capital İ
    assert tidy_label("ılıca") == "Ilıca"
    assert tidy_label("  Eyfel Kulesi ") == "Eyfel Kulesi"


def test_tidy_label_drops_the_city_that_wikipedia_titles_add() -> None:
    paris = {"Paris", "paris"}
    assert tidy_label("Saint-Eustache, Paris", paris) == "Saint-Eustache"
    assert tidy_label("Ulusal Doğa Tarihi Müzesi (Paris)", paris) == "Ulusal Doğa Tarihi Müzesi"
    assert tidy_label("Pont Neuf (köprü)", paris) == "Pont Neuf (köprü)"  # not the city: kept
    assert tidy_label("Paris", paris) == "Paris"  # nothing would be left


def test_fit_cuts_long_texts_at_a_word() -> None:
    assert fit("short enough", 300) == "short enough"
    text = "word " * 100
    cut = fit(text, 50)
    assert len(cut) <= 50 and cut.endswith("…") and not cut.endswith(" …")
    assert cut.removesuffix("…").split() == ["word"] * len(cut.removesuffix("…").split())


def test_second_listings_are_the_less_reviewed_places_of_an_item() -> None:
    rows = [  # most reviewed first, as the query returns them
        SimpleNamespace(id="palace", wikidata_id="Q1"),
        SimpleNamespace(id="harem", wikidata_id="Q1"),
        SimpleNamespace(id="tower", wikidata_id="Q2"),
        SimpleNamespace(id="park", wikidata_id=None),
    ]
    assert second_listings(rows) == {"harem"}


# --- clients --------------------------------------------------------------------------------------


def test_translate_client_sends_plain_text_in_batches_and_counts_characters() -> None:
    bodies: list[dict] = []

    def api(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Goog-Api-Key"] == "key"  # in a header, not the URL
        assert "key" not in str(request.url)
        body = json.loads(request.content)
        bodies.append(body)
        return httpx.Response(200, json={"data": {"translations": [{"translatedText": t.upper()} for t in body["q"]]}})

    with TranslateClient("key", transport=httpx.MockTransport(api)) as client:
        texts = [f"text {i}" for i in range(60)]
        assert client.translate(texts, "en", "tr") == [t.upper() for t in texts]
        assert client.characters == sum(len(t) for t in texts)
    assert [len(b["q"]) for b in bodies] == [50, 10]
    assert {(b["source"], b["target"], b["format"]) for b in bodies} == {("en", "tr", "text")}


def test_translate_client_does_not_resend_after_a_timeout() -> None:
    calls = 0

    def api(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("no answer", request=request)  # Google may have billed it already

    with TranslateClient("key", transport=httpx.MockTransport(api)) as client, pytest.raises(TranslateError):
        client.translate(["hello"], "en", "tr")
    assert calls == 1


def test_translate_client_reports_errors() -> None:
    def api(_: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"message": "Cloud Translation API has not been used"}})

    with TranslateClient("key", transport=httpx.MockTransport(api)) as client, pytest.raises(TranslateError) as e:
        client.translate(["hello"], "en", "tr")
    assert "403" in str(e.value) and "not been used" in str(e.value)
    assert client.characters == 0  # nothing billed


def test_display_name_asks_place_details_in_the_language() -> None:
    def api(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET" and request.url.path == "/v1/places/abc"
        assert request.url.params["languageCode"] == "tr"
        assert request.headers["X-Goog-FieldMask"] == "displayName"  # the Pro SKU field only
        return httpx.Response(200, json={"displayName": {"text": "Mısır Çarşısı", "languageCode": "tr"}})

    with PlacesClient("key", transport=httpx.MockTransport(api)) as client:
        assert client.display_name("abc", "tr") == ("Mısır Çarşısı", "tr")
        assert client.requests["names"] == 1


def test_display_name_of_a_place_gone_from_google() -> None:
    def api(_: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": {"message": "Not found"}})

    with PlacesClient("key", transport=httpx.MockTransport(api)) as client, pytest.raises(PlacesAPIError) as e:
        client.display_name("gone", "tr")
    assert e.value.status_code == 404


def test_wikidata_labels_in_one_language() -> None:
    asked: list[dict] = []

    def api(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        asked.append(params)
        entities = {
            qid: {"labels": {"tr": {"language": "tr", "value": f"{qid} adı"}}} if qid != "Q3" else {"labels": {}}
            for qid in params["ids"].split("|")
        }
        return httpx.Response(200, json={"entities": entities})

    with WikiClient(transport=httpx.MockTransport(api), pause_s=0) as wiki:
        assert wiki.labels(["Q1", "Q2", "Q3"], "tr") == {"Q1": "Q1 adı", "Q2": "Q2 adı"}
    assert asked[0]["action"] == "wbgetentities" and asked[0]["languages"] == "tr" and asked[0]["props"] == "labels"

"""Short descriptions of places from Wikipedia, matched through Wikidata.

Google gives a place's name and position, not what it is. To describe it, each place is matched
to its Wikidata item (the open database behind Wikipedia):

1. English Wikipedia is searched for the place's name. An article counts if it lies near the
   place and its name agrees.
2. If none does, the Wikidata items around the place are compared with its name. That finds
   places whose article goes by another name, or that only have a Turkish article.

Names agree when their words match, and words for the kind of place must not contradict each
other: "Jardin du Luxembourg" is not the Luxembourg Palace, and "Galata Tower" is not the Galata
neighbourhood. A bare name ("Hagia Sophia" for "Hagia Sophia Grand Mosque") only counts when the
item's description names the right kind of place ("mosque and former church in Istanbul").

The description is the first sentence or two of the Turkish and the English article, without the
parentheses (other names, pronunciations). Wikipedia's text is CC BY-SA 4.0: the app shows it
with a link to the article and says that it was shortened. Requests go one at a time, as
Wikimedia asks of API clients.
"""

import re
import time
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Protocol

import httpx

from app.services.geo import LatLng, haversine_km

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
WIKIPEDIA_API = "https://{lang}.wikipedia.org/w/api.php"
# Wikimedia asks API clients to say who they are and how to reach them.
USER_AGENT = "NoloRoute/0.1 (https://github.com/bukrathezer/noloroute)"

LANGUAGES = ("tr", "en")  # the app's languages: one description in each
MATCH_THRESHOLD = 0.75
SEARCH_RESULTS = 5
NEARBY_LIMIT = 100
RETRIES = 5  # for throttled or busy answers, with a growing wait in between
DEFAULT_RADIUS_M = 600
# How far an article's coordinates may lie from Google's pin. Parks and districts are big.
RADIUS_M = {"PARK": 1500, "VIEWPOINT": 1000}
AREA_RADIUS_M = 1500
DESCRIPTION_MAX = 220  # characters; a longer first sentence is cut short with "…"
DESCRIPTION_ENOUGH = 80  # a second sentence is added only to a shorter first one,
DESCRIPTION_TWO_MAX = 180  # and only if both together stay this short
DESCRIPTION_MIN = 50

# The language a city's places are named in locally, for Wikidata's labels (by country code).
COUNTRY_LANGUAGE = {
    "AE": "ar", "AT": "de", "AZ": "az", "BA": "bs", "BE": "fr", "CZ": "cs", "DE": "de", "DK": "da",
    "ES": "es", "FR": "fr", "GB": "en", "GE": "ka", "GR": "el", "HU": "hu", "IT": "it", "JP": "ja",
    "KR": "ko", "MA": "fr", "NL": "nl", "PT": "pt", "RS": "sr", "SE": "sv", "SG": "en", "TH": "th",
    "TR": "tr", "US": "en",
}  # fmt: skip

# Words for kinds of places, in the languages Google's and Wikipedia's names come in (accents
# removed). Names are compared without them; the kinds themselves must agree.
KIND_WORDS = {
    "museum": "museum musee museo museu muzesi muze muzeum gallery galleria galerie",
    "mosque": "mosque camii cami camisi mescidi mosquee moschea moschee mezquita",
    "church": "church eglise chiesa kilisesi basilica basilique bazilikasi chapel chapelle cappella sapeli "
    "cathedral cathedrale catedral katedrali duomo kirche kerk iglesia igreja capilla kapelle",
    "synagogue": "synagogue sinagogu sinagoga",
    "palace": "palace palais palazzo palacio palast paleis sarayi",
    "park": "park parki parc parco parque korusu koru",
    "garden": "garden gardens jardin jardins jardines jardim giardino giardini garten tuin bahcesi",
    "tower": "tower tour torre turm toren kulesi",
    "bridge": "bridge pont ponte puente brucke brug koprusu",
    "square": "square place piazza plaza placa platz plein praca namesti meydani",
    "market": "market marche mercato mercado mercat markt pazari carsi carsisi bazaar bazar",
    "temple": "temple tempel templo tempio tapinagi",
    "shrine": "shrine jinja taisha jingu",
    "station": "station gare stazione estacion bahnhof hauptbahnhof istasyonu",
    "fountain": "fountain fontaine fontana fuente brunnen cesmesi",
    "castle": "castle chateau castello castillo castelo schloss kasteel fortress hisari kalesi",
    "gate": "gate porte porta puerta tor kapisi",
    "hill": "hill colle tepesi butte",
    "street": "street rue via calle strasse straat gasse rua avenida avenue boulevard caddesi sokagi bulvari",
    "cemetery": "cemetery cimetiere cimitero cementerio cemiterio friedhof mezarligi",
    "beach": "beach coast seaside shore waterfront plage spiaggia playa praia strand plaji sahil sahili",
    "statue": "statue heykeli statua",
}
_KIND_OF = {word: kind for kind, words in KIND_WORDS.items() for word in words.split()}
# Different words that can still name the same place: a palace or castle that is now a museum.
_RELATED_KINDS = [
    {"park", "garden"},
    {"park", "beach"},
    {"museum", "palace"},
    {"museum", "castle"},
    {"tower", "castle"},
]
_STOPWORDS = frozenset(
    {"the", "of", "and", "a", "an", "in", "on", "at", "e", "et", "ve", "al", "el"}
    | {"de", "du", "des", "la", "le", "les", "l", "d", "di", "del", "della", "dello", "dei", "degli", "delle"}
    | {"da", "do", "das", "dos", "ibb"}  # ibb: Istanbul's municipality, in front of many park names
)
# Kind words that mean something else in an English description ("place of worship").
_NOT_KINDS_IN_ENGLISH = frozenset({"place", "via", "tour", "porte", "porta"})
_SAME_WORD = {"st": "saint", "ste": "sainte", "san": "saint", "santo": "saint", "sankt": "saint"}
# Descriptions of areas rather than sights. A neighbourhood's item can carry its square's name
# ("Ortaköy Meydanı" on Ortaköy), so areas only match places that are districts themselves.
_AREA = re.compile(
    r"\b(neighbou?rhood|district|quarter|mahalle|arrondissement|municipality|commune|village|ward|borough|suburb|"
    r"human settlement|rione|quartiere|capital|(city|town) (in|of))\b",
    re.IGNORECASE,
)
_POSSESSIVE = re.compile(r"['’`]s\b")  # Peter's -> Peter


class WikiError(Exception):
    pass


# ---------- names ----------


def _words(name: str) -> list[str]:
    text = name.replace("İ", "i").replace("ı", "i").casefold()
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    text = re.sub(r"[^\w\s]", " ", _POSSESSIVE.sub("", text))
    return [_SAME_WORD.get(w, w) for w in text.split() if w not in _STOPWORDS]


def _split(name: str) -> tuple[list[str], set[str]]:
    """A name's own words and the kinds of place it says it is."""
    words, kinds = [], set()
    for word in _words(name):
        if word in _KIND_OF:
            kinds.add(_KIND_OF[word])
        else:
            words.append(word)
    return words, kinds


def _related(kind: str, kinds: set[str]) -> bool:
    return kind in kinds or any(kind in group and kinds & group for group in _RELATED_KINDS)


def _kinds_agree(place: set[str], candidate: set[str]) -> bool:
    """Every kind a candidate's name gives must fit the place's: "Yoğurtçu Parkı Çeşmesi" is a
    fountain in the park, not the park."""
    return not place or all(_related(kind, place) for kind in candidate)


def _same_word(a: str, b: str) -> bool:
    # Spelling variants: "trocadero"/"trocadéro", "catacombe"/"catacomb".
    return a == b or (min(len(a), len(b)) > 3 and SequenceMatcher(None, a, b).ratio() >= 0.8)


def name_score(place_name: str, candidate_name: str, candidate_description: str = "") -> float:
    """How well a Wikipedia/Wikidata name fits a place's name, from 0 to 1."""
    place_words, place_kinds = _split(place_name)
    cand_words, cand_kinds = _split(candidate_name)
    described_kinds = {
        _KIND_OF[w] for w in _words(candidate_description) if w in _KIND_OF and w not in _NOT_KINDS_IN_ENGLISH
    }
    if "disambiguation" in candidate_description.casefold():
        return 0.0
    if "station" in cand_kinds | described_kinds and "station" not in place_kinds:
        return 0.0  # "Kurumazaki-Jinja Station" is not Kurumazaki Shrine
    if not _kinds_agree(place_kinds, cand_kinds):
        return 0.0
    if place_kinds and not cand_kinds and not any(_related(kind, place_kinds) for kind in described_kinds):
        return 0.0  # a bare "Galata" for "Galata Tower": only if the item says it is a tower
    if not place_words or not cand_words:
        return 0.0

    hits, used = 0, set()
    for word in place_words:
        match = next((j for j, other in enumerate(cand_words) if j not in used and _same_word(word, other)), None)
        if match is not None:
            used.add(match)
            hits += 1
    if hits == len(place_words) == len(cand_words):
        return 1.0
    # Same letters, split differently: "Sanjūsangendō" and "Sanjūsangen-dō".
    joined = SequenceMatcher(None, "".join(place_words), "".join(cand_words)).ratio()
    if joined >= 0.9:
        return joined
    if hits == len(cand_words):
        # Wikipedia's name is the shorter one: "Kyoto Tower" for "Nidec Kyoto Tower". Fine when
        # the kinds were confirmed above, or when the shared words are half the name or more,
        # but not when only the candidate names a kind ("Nakkaştepe Mezarlığı", a cemetery, for
        # "Zippline Nakkaştepe").
        if cand_kinds and not place_kinds:
            return 0.0
        return 0.85 if place_kinds or 2 * hits >= len(place_words) else 0.0
    return hits / max(len(place_words), len(cand_words))


# ---------- descriptions ----------

_ROMAN_NUMERAL = re.compile(r"^[IVXLC]+$")
_ABBREVIATIONS = frozenset(
    {"st", "ste", "dr", "mr", "mrs", "ms", "mt", "jr", "sr", "ca", "c", "approx", "vs", "etc", "no", "inc", "ltd"}
    | {"co", "yy", "vb", "örn", "bkz", "m.ö", "m.s", "hz", "prof", "doç", "sok", "cad", "mah"}  # Turkish ones
)
_SENTENCE_END = re.compile(r"[.!?](?=\s+[\"'“‘]?[A-ZÇĞİÖŞÜ0-9])")


def _sentences(text: str, lang: str) -> list[str]:
    sentences, start = [], 0
    for end in _SENTENCE_END.finditer(text):
        before = text[start : end.start()].split()
        word = before[-1].strip("\"'“”‘’") if before else ""
        if end.group() == "." and (
            len(word) == 1
            or _ROMAN_NUMERAL.match(word)  # "IX. Louis", "II. Dünya Savaşı"
            or word.casefold() in _ABBREVIATIONS
            or (lang == "tr" and word.isdigit())  # Turkish ordinals: "2. Dünya Savaşı"
        ):
            continue
        sentences.append(text[start : end.end()].strip())
        start = end.end()
    if text[start:].strip():
        sentences.append(text[start:].strip())
    return sentences


def shorten(intro: str, lang: str) -> str | None:
    """The first sentence or two of an article's introduction, without the parentheses."""
    text = intro.strip().split("\n")[0]
    previous = None
    while previous != text:  # innermost parentheses first: "(Greek: ... (Basilica))"
        previous, text = text, re.sub(r"\s*\([^()]*\)", "", text)
    text = re.sub(r"\s+([,.;:])", r"\1", " ".join(text.split()))
    # Too short to say anything ("Kadırga Park is a park in Istanbul, Turkey."), or a page that
    # lists several places of that name.
    if len(text) < DESCRIPTION_MIN or "may refer to" in text or "şu anlamlara gelebilir" in text:
        return None

    first, *rest = _sentences(text, lang)
    if len(first) > DESCRIPTION_MAX:
        return first[: DESCRIPTION_MAX - 1].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    if len(first) < DESCRIPTION_ENOUGH and rest and len(first) + 1 + len(rest[0]) <= DESCRIPTION_TWO_MAX:
        first = f"{first} {rest[0]}"
    return first if len(first) >= DESCRIPTION_MIN else None


# ---------- the APIs ----------


@dataclass
class Entity:
    """The parts of a Wikidata item the matching uses."""

    qid: str
    names: list[str]  # labels and aliases in the languages asked for
    description: str  # English, e.g. "mosque in Istanbul, Turkey"
    articles: dict[str, str]  # Wikipedia article titles by language, for LANGUAGES only
    sitelink_count: int  # how many Wikipedias have an article: a popularity signal


@dataclass
class Match:
    qid: str
    articles: dict[str, str]
    score: float
    distance_m: float
    via: str  # "search" or "nearby"


class WikiApi(Protocol):
    def search(self, name: str) -> list[tuple[str, LatLng]]: ...
    def nearby(self, where: LatLng, radius_m: int) -> dict[str, float]: ...
    def entities(self, qids: Sequence[str], languages: Iterable[str]) -> dict[str, Entity]: ...
    def intros(self, lang: str, titles: Sequence[str]) -> dict[str, str]: ...


@dataclass
class WikiClient:
    """Calls to the Wikipedia and Wikidata APIs, one at a time, with retries when throttled."""

    timeout: float = 30.0
    pause_s: float = 0.05  # between requests, to stay well within Wikimedia's limits
    retry_wait_s: float = 5.0  # then 10 s, 15 s, ... before each retry
    transport: httpx.BaseTransport | None = None  # lets tests answer without the network
    requests: int = 0
    _http: httpx.Client = field(init=False)

    def __post_init__(self) -> None:
        self._http = httpx.Client(timeout=self.timeout, transport=self.transport, headers={"User-Agent": USER_AGENT})

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "WikiClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        problem = ""
        for attempt in range(RETRIES + 1):
            if attempt:
                time.sleep(self.retry_wait_s * attempt)
            self.requests += 1
            try:
                resp = self._http.get(url, params={**params, "format": "json", "formatversion": 2})
            except httpx.HTTPError as e:
                problem = str(e)
                continue
            if resp.status_code in (429, 503):  # throttled or overloaded: wait as long as asked
                problem = f"answered {resp.status_code}"
                time.sleep(_retry_after(resp))
                continue
            if resp.status_code != 200:
                raise WikiError(f"{url} answered {resp.status_code}")
            data = resp.json()
            error = data.get("error")
            if error:
                problem = str(error.get("info", error))
                # "Search is currently too busy. Please try again later." and the like pass.
                if error.get("code") in ("maxlag", "ratelimited") or "try again" in problem.casefold():
                    continue
                raise WikiError(f"{url}: {problem}")
            time.sleep(self.pause_s)
            return data
        raise WikiError(f"{url}: {problem} (gave up after {RETRIES} retries)")

    def search(self, name: str) -> list[tuple[str, LatLng]]:
        """English Wikipedia articles found for a name, best first: (Wikidata id, coordinates)."""
        data = self._get(
            WIKIPEDIA_API.format(lang="en"),
            {
                "action": "query",
                "generator": "search",
                "gsrsearch": name,
                "gsrlimit": SEARCH_RESULTS,
                "prop": "coordinates|pageprops",
                "ppprop": "wikibase_item",
                "colimit": "max",
            },
        )
        found = []
        for page in sorted(data.get("query", {}).get("pages", []), key=lambda p: p.get("index", 0)):
            qid = page.get("pageprops", {}).get("wikibase_item")
            coords = page.get("coordinates") or []
            if qid and coords:
                found.append((qid, LatLng(coords[0]["lat"], coords[0]["lon"])))
        return found

    def nearby(self, where: LatLng, radius_m: int) -> dict[str, float]:
        """Wikidata items within a radius: {Wikidata id: distance in metres}, nearest first."""
        data = self._get(
            WIKIDATA_API,
            {
                "action": "query",
                "list": "geosearch",
                "gscoord": f"{where.lat}|{where.lng}",
                "gsradius": radius_m,
                "gslimit": NEARBY_LIMIT,
            },
        )
        return {item["title"]: item["dist"] for item in data.get("query", {}).get("geosearch", [])}

    def entities(self, qids: Sequence[str], languages: Iterable[str]) -> dict[str, Entity]:
        langs = sorted(set(languages))
        result: dict[str, Entity] = {}
        for i in range(0, len(qids), 50):  # the API's batch limit
            data = self._get(
                WIKIDATA_API,
                {
                    "action": "wbgetentities",
                    "ids": "|".join(qids[i : i + 50]),
                    "props": "labels|aliases|descriptions|sitelinks",
                    "languages": "|".join(langs),
                },
            )
            for qid, item in data.get("entities", {}).items():
                if "missing" in item:
                    continue
                names = [label["value"] for label in item.get("labels", {}).values()]
                names += [alias["value"] for aliases in item.get("aliases", {}).values() for alias in aliases]
                sitelinks = item.get("sitelinks", {})
                result[qid] = Entity(
                    qid=qid,
                    names=names,
                    description=item.get("descriptions", {}).get("en", {}).get("value", ""),
                    articles={
                        lang: sitelinks[f"{lang}wiki"]["title"] for lang in LANGUAGES if f"{lang}wiki" in sitelinks
                    },
                    sitelink_count=len(sitelinks),
                )
        return result

    def intros(self, lang: str, titles: Sequence[str]) -> dict[str, str]:
        """Plain-text introductions of Wikipedia articles, keyed by the titles asked for."""
        result: dict[str, str] = {}
        for i in range(0, len(titles), 20):  # the most intros the API returns at once
            batch = titles[i : i + 20]
            data = self._get(
                WIKIPEDIA_API.format(lang=lang),
                {
                    "action": "query",
                    "prop": "extracts",
                    "exintro": 1,
                    "explaintext": 1,
                    "exlimit": 20,
                    "redirects": 1,
                    "titles": "|".join(batch),
                },
            )
            query = data.get("query", {})
            # Titles come back normalized ("Galata_Tower" -> "Galata Tower") or redirected.
            renamed = {r["to"]: r["from"] for r in [*query.get("normalized", []), *query.get("redirects", [])]}
            for page in query.get("pages", []):
                title = page.get("title", "")
                while title in renamed and title not in batch:
                    title = renamed[title]
                if page.get("extract") and title in batch:
                    result[title] = page["extract"]
        return result


def _retry_after(resp: httpx.Response) -> float:
    try:
        return min(float(resp.headers.get("Retry-After", 0)), 120)
    except ValueError:  # an HTTP date instead of seconds: the growing wait covers it
        return 0


# ---------- matching ----------


def _best(
    place_name: str, entities: dict[str, Entity], distances: dict[str, float], via: str, is_area: bool
) -> Match | None:
    best: tuple[tuple[float, int, float], Match] | None = None
    for qid, entity in entities.items():
        if not entity.articles:
            continue  # nothing to describe it with
        if not is_area and _AREA.search(entity.description):
            continue
        score = max((name_score(place_name, name, entity.description) for name in entity.names), default=0.0)
        if score < MATCH_THRESHOLD:
            continue
        key = (round(score, 2), entity.sitelink_count, -distances[qid])
        if best is None or key > best[0]:
            best = (key, Match(qid, entity.articles, score, distances[qid], via))
    return best[1] if best else None


def match_place(
    api: WikiApi, name: str, where: LatLng, category: str, local_language: str, is_area: bool = False
) -> Match | None:
    """The Wikidata item of a place, if one fits its name and position well enough.

    `is_area`: the place is a district or a street itself (Montmartre, Balat, İstiklal Avenue).
    """
    radius_m = AREA_RADIUS_M if is_area else RADIUS_M.get(category, DEFAULT_RADIUS_M)
    languages = {*LANGUAGES, local_language}
    found = {}
    for qid, at in api.search(name):
        distance_m = haversine_km(where, at) * 1000
        if distance_m <= radius_m:
            found.setdefault(qid, distance_m)
    match = _best(name, api.entities(list(found), languages), found, "search", is_area) if found else None
    if match is None:
        near = api.nearby(where, radius_m)
        if near:
            match = _best(name, api.entities(list(near), languages), near, "nearby", is_area)
    return match


def describe(api: WikiApi, matches: Iterable[Match]) -> dict[str, dict[str, str]]:
    """Short descriptions for matched items: {Wikidata id: {language: text}}."""
    texts: dict[str, dict[str, str]] = {}
    matches = list(matches)
    for lang in LANGUAGES:
        qid_of = {m.articles[lang]: m.qid for m in matches if lang in m.articles}
        for title, intro in api.intros(lang, list(qid_of)).items():
            short = shorten(intro, lang)
            if short:
                texts.setdefault(qid_of[title], {})[lang] = short
    return texts

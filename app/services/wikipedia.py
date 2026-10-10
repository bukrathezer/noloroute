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
WDQS_URL = "https://query.wikidata.org/sparql"  # Wikidata's SPARQL endpoint, for famous_places
# Wikimedia asks API clients to say who they are and how to reach them.
USER_AGENT = "NoloRoute/0.1 (https://github.com/bukrathezer/noloroute)"

LANGUAGES = ("tr", "en")  # the app's languages: one description in each
MATCH_THRESHOLD = 0.75
SEARCH_RESULTS = 5
NEARBY_LIMIT = 100
RETRIES = 5  # for throttled or busy answers, with a growing wait in between
FAMOUS_MIN_SITELINKS = 20  # Wikipedia articles in this many languages make a place famous
# What Wikidata's classes for an item must say for famous_places to count it as a sight: a
# museum, church, bridge, square... A university, a station or an event is not, nor is a work of
# art kept in a museum (the Venus de Milo is in the Louvre), nor a building that is gone.
_SIGHT_CLASS = re.compile(
    r"museum|gallery|church|cathedral|basilica|chapel|abbey|monastery|mosque|synagogue|temple|shrine|palace|"
    r"castle|fortress|\bfort\b|citadel|tower|bridge|square|plaza|park|garden|cemetery|monument|memorial|fountain|"
    r"gate|arch\b|column|obelisk|market|bazaar|observatory|skyscraper|opera house|amphitheat|ruins|"
    r"archaeological site|forum|aqueduct|city wall|cistern|mausoleum|tomb|pagoda|viewpoint|aquarium|landmark|"
    r"tourist attraction|historic house|villa|statue",
    re.IGNORECASE,
)
_NOT_SIGHT_CLASS = re.compile(
    r"station|university|school|college|hospital|embassy|hotel|company|ministry|district|neighbo|arrondissement|"
    r"commune|municipality|railway|metro|transit|event|battle|treaty|language|sports team|club|stadium|airport|"
    r"painting|artefact|artifact|destroyed|demolished|former|official residence",
    re.IGNORECASE,
)
DEFAULT_RADIUS_M = 600
# How far an article's coordinates may lie from Google's pin. Parks and districts are big.
RADIUS_M = {"PARK": 1500, "VIEWPOINT": 1000}
AREA_RADIUS_M = 1500
NEAR_M = 300  # a match this close is the place itself, more likely than a farther namesake
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
    "square": "square place piazza plaza placa platz plein praca namesti meydani parvis esplanade",
    "market": "market marche mercato mercado mercat markt pazari carsi carsisi bazaar bazar",
    "temple": "temple tempel templo tempio tapinagi",
    "shrine": "shrine jinja taisha jingu",
    "station": "station stop gare stazione estacion bahnhof hauptbahnhof istasyonu",
    "fountain": "fountain fontaine fontana fuente brunnen cesmesi",
    "castle": "castle chateau castel castello castillo castelo schloss kasteel fortress hisari kalesi",
    "gate": "gate porte porta puerta tor kapisi",
    "hill": "hill colle tepesi butte",
    "street": "street rue via calle strasse straat gasse rua avenida avenue boulevard caddesi sokagi bulvari",
    "cemetery": "cemetery cimetiere cimitero cementerio cemiterio friedhof mezarligi",
    "tomb": "tomb grave tombe tomba tumba grab mausoleum turbe turbesi kabri",
    "beach": "beach coast seaside shore waterfront plage spiaggia playa praia strand plaji sahil sahili",
    "pool": "pool pools bassin bassins havuzu",
    "cistern": "cistern cisterna sarnic sarnici",
    "wall": "wall walls mura muralla surlari suru",
    "statue": "statue heykeli statua",
}
_KIND_OF = {word: kind for kind, words in KIND_WORDS.items() for word in words.split()}
# What a place of each of our categories can be, for names that don't say it themselves: "La
# Madeleine" is a church, so "Boulevard de la Madeleine" is not it. Landmarks can be anything.
CATEGORY_KINDS = {
    "MUSEUM": {"museum", "palace", "castle"},
    "RELIGIOUS_SITE": {"mosque", "church", "synagogue", "temple", "shrine", "tomb", "cemetery"},
    "PARK": {"park", "garden", "square", "beach", "hill", "cemetery"},  # a Paris "square" is a park
    "MARKET": {"market", "street", "square"},
}
# Different words that can still name the same place: a palace that is now a museum, a market
# that is a street.
_RELATED_KINDS = [
    {"park", "garden"},
    {"park", "beach"},
    {"museum", "palace"},
    {"museum", "castle"},
    {"tower", "castle"},
    {"market", "street"},
]
_PREPOSITIONS = frozenset({"of", "de", "du", "des", "d", "di", "del", "della", "dello", "dei", "degli", "delle"})
_STOPWORDS = (
    _PREPOSITIONS
    | {"the", "and", "a", "an", "in", "on", "at", "e", "et", "ve", "al", "el", "la", "le", "les", "l"}
    | {"da", "do", "das", "dos", "ibb"}  # ibb: Istanbul's municipality, in front of many park names
)
# Kind words that mean something else in an English description ("place of worship").
_NOT_KINDS_IN_ENGLISH = frozenset({"place", "via", "tour", "porte", "porta"})
_SAME_WORD = {"st": "saint", "ste": "sainte", "san": "saint", "santo": "saint", "sankt": "saint"}
# What areas are called in Wikidata's descriptions: "mahalle (administrative quarter) in
# Beşiktaş", "historic district of Paris". A neighbourhood's item can carry its square's name
# ("Ortaköy Meydanı" on Ortaköy), so areas only match places that are districts themselves.
_AREA_NOUNS = frozenset(
    {"neighbourhood", "neighborhood", "district", "quarter", "mahalle", "arrondissement", "municipality", "commune"}
    | {"village", "hamlet", "ward", "borough", "suburb", "settlement", "rione", "quartiere", "capital", "city"}
    | {"town", "area", "region", "province"}
)
_POSSESSIVE = re.compile(r"['’`]s\b")  # Peter's -> Peter
# Wikidata's badges for a link to a redirect: the article it leads to is about something else
# ("Grave of Jim Morrison" redirects to the singer's article).
_REDIRECT_BADGES = frozenset({"Q70893996", "Q70894304"})


class WikiError(Exception):
    pass


# ---------- names ----------


def _tokens(name: str) -> list[str]:
    text = name.replace("İ", "i").replace("ı", "i").casefold()
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    text = re.sub(r"[^\w\s]", " ", _POSSESSIVE.sub("", text))
    return [_SAME_WORD.get(w, w) for w in text.split()]


def _words(name: str) -> list[str]:
    return [w for w in _tokens(name) if w not in _STOPWORDS]


def _split(name: str) -> tuple[list[str], set[str]]:
    """A name's own words and all the kinds of place it mentions."""
    words, kinds = [], set()
    for word in _words(name):
        if word in _KIND_OF:
            kinds.add(_KIND_OF[word])
        else:
            words.append(word)
    if not words:
        # Only kind words, as in "Basilica Cistern": all but the head kind name the place.
        head = head_kind(name)
        words = [w for w in _words(name) if _KIND_OF.get(w) != head]
    return words, kinds


def head_kind(name: str) -> str | None:
    """The kind of place a name says its place is, when it says so: the first kind word when a
    preposition follows it ("Jardin de la Tour Eiffel" is a garden, "Square of Saint-Jacques
    Tower" a square), otherwise the last ("Topkapı Palace Museum" is a museum, "Yoğurtçu Parkı
    Çeşmesi" a fountain)."""
    tokens = _tokens(name)
    kinds = [(i, _KIND_OF[t]) for i, t in enumerate(tokens) if t in _KIND_OF]
    if not kinds:
        return None
    first, kind = kinds[0]
    if first + 1 < len(tokens) and tokens[first + 1] in _PREPOSITIONS:
        return kind
    return kinds[-1][1]


def _related(kind: str, kinds: set[str]) -> bool:
    return kind in kinds or any(kind in group and kinds & group for group in _RELATED_KINDS)


def _same_word(a: str, b: str) -> bool:
    # Spelling variants: "trocadero"/"trocadéro", "catacombe"/"catacomb".
    return a == b or (min(len(a), len(b)) > 3 and SequenceMatcher(None, a, b).ratio() >= 0.8)


def describes_area(description: str) -> bool:
    """Whether a Wikidata description says the item is an area ("historic district of Paris"),
    not just where it is ("square in the 8th arrondissement of Paris")."""
    text = re.sub(r"\([^)]*\)", " ", description.casefold())
    head = re.split(r"\s(?:in|of|on|at|near|within)\s|,", text, maxsplit=1)[0].split()
    return bool(head) and head[-1] in _AREA_NOUNS


def name_score(place_name: str, candidate_name: str, candidate_description: str = "", category: str = "") -> float:
    """How well a Wikipedia/Wikidata name fits a place's name, from 0 to 1. `category` is the
    place's own (MUSEUM, PARK, ...)."""
    place_words, place_kinds = _split(place_name)
    cand_words, cand_kinds = _split(candidate_name)
    place_head, cand_head = head_kind(place_name), head_kind(candidate_name)
    described_kinds = {
        _KIND_OF[w] for w in _words(candidate_description) if w in _KIND_OF and w not in _NOT_KINDS_IN_ENGLISH
    }
    # What the place is: what its name says, or else what its category allows.
    expected = {place_head} if place_head else CATEGORY_KINDS.get(category, set())
    if "disambiguation" in candidate_description.casefold():
        return 0.0
    if "station" in cand_kinds | described_kinds and "station" not in place_kinds:
        return 0.0  # "Kurumazaki-Jinja Station" is not Kurumazaki Shrine
    if expected and cand_head and not _related(cand_head, expected):
        return 0.0  # the Luxembourg Palace is not the Jardin du Luxembourg, a fountain not its park
    if place_head and not cand_head and not any(_related(kind, {place_head}) for kind in described_kinds):
        return 0.0  # a bare "Galata" for "Galata Tower": only if the item says it is a tower
    if not place_words or not cand_words:
        return 0.0
    score = _word_score(place_words, cand_words, place_head is not None, cand_head is not None)
    # A related kind (the Luxembourg Palace for the museum in it) loses to the exact one.
    return score * 0.95 if place_head and cand_head and cand_head != place_head else score


def _word_score(place_words: list[str], cand_words: list[str], place_has_kind: bool, cand_has_kind: bool) -> float:
    hits, used = 0, set()
    for word in place_words:
        match = next((j for j, other in enumerate(cand_words) if j not in used and _same_word(word, other)), None)
        if match is not None:
            used.add(match)
            hits += 1
    if hits == len(place_words) == len(cand_words):
        return 1.0
    # Same letters, split into words differently: "Sanjūsangendō" and "Sanjūsangen-dō". (With as
    # many words on both sides, "Walls of Constantinople" isn't "Fall of Constantinople".)
    if len(place_words) != len(cand_words):
        joined = SequenceMatcher(None, "".join(place_words), "".join(cand_words)).ratio()
        if joined >= 0.9:
            return joined
    if hits == len(cand_words):
        # Wikipedia's name is the shorter one: "Kyoto Tower" for "Nidec Kyoto Tower". Fine when
        # the kinds were confirmed, or when the shared words are half the name or more, but not
        # when only the candidate names a kind ("Nakkaştepe Mezarlığı", a cemetery, for
        # "Zippline Nakkaştepe").
        if cand_has_kind and not place_has_kind:
            return 0.0
        return 0.85 if place_has_kind or 2 * hits >= len(place_words) else 0.0
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
    sitelink_count: int
    via: str  # "search" or "nearby"

    def rank(self) -> tuple[float, bool, int, float]:
        """Better matches first: the name, then being right there, then fame, then closeness."""
        return (round(self.score, 2), self.distance_m <= NEAR_M, self.sitelink_count, -self.distance_m)


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
            # The MediaWiki APIs take formatversion 2 (lists instead of id-keyed objects); SPARQL doesn't.
            query = (
                {**params, "format": "json"} if url == WDQS_URL else {**params, "format": "json", "formatversion": 2}
            )
            try:
                resp = self._http.get(url, params=query)
            except httpx.HTTPError as e:
                problem = str(e)
                continue
            if resp.status_code in (429, 500, 502, 503, 504):  # throttled or overloaded: wait and retry
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
                own_articles = {
                    lang: link["title"]
                    for lang in LANGUAGES
                    if (link := sitelinks.get(f"{lang}wiki")) and not _REDIRECT_BADGES & set(link.get("badges", []))
                }
                result[qid] = Entity(
                    qid=qid,
                    names=names,
                    description=item.get("descriptions", {}).get("en", {}).get("value", ""),
                    articles=own_articles,
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

    def famous_places(
        self, centre: LatLng, radius_km: float, min_sitelinks: int = FAMOUS_MIN_SITELINKS
    ) -> list["FamousPlace"]:
        """Sights with Wikipedia articles in at least `min_sitelinks` languages around a point,
        most famous first (see is_sight_class for what counts as a sight)."""
        query = f"""
SELECT ?item ?label ?links ?coord (GROUP_CONCAT(DISTINCT ?classLabel; separator="|") AS ?classes) WHERE {{
  SERVICE wikibase:around {{
    ?item wdt:P625 ?coord .
    bd:serviceParam wikibase:center "Point({centre.lng} {centre.lat})"^^geo:wktLiteral .
    bd:serviceParam wikibase:radius "{radius_km:.1f}" .
  }}
  ?item wikibase:sitelinks ?links . FILTER(?links >= {min_sitelinks})
  ?item rdfs:label ?label . FILTER(LANG(?label) = "en")
  ?item wdt:P31 ?class . ?class rdfs:label ?classLabel . FILTER(LANG(?classLabel) = "en")
}} GROUP BY ?item ?label ?links ?coord ORDER BY DESC(?links)"""
        rows = self._get(WDQS_URL, {"query": query}).get("results", {}).get("bindings", [])
        places, seen = [], set()
        for row in rows:
            qid = row["item"]["value"].rsplit("/", 1)[-1]
            point = re.findall(r"-?\d+(?:\.\d+)?", row["coord"]["value"])  # "Point(lng lat)"
            if qid in seen or len(point) < 2 or not is_sight_class(row["classes"]["value"]):
                continue
            seen.add(qid)
            places.append(
                FamousPlace(
                    qid=qid,
                    label=row["label"]["value"],
                    classes=row["classes"]["value"],
                    sitelink_count=int(row["links"]["value"]),
                    where=LatLng(float(point[1]), float(point[0])),
                )
            )
        return places

    def sitelink_counts(self, qids: Sequence[str]) -> dict[str, int]:
        """How many Wikimedia sites have an article on each item: {Wikidata id: count}."""
        counts: dict[str, int] = {}
        for i in range(0, len(qids), 200):  # a few hundred ids keep a query short
            values = " ".join(f"wd:{qid}" for qid in qids[i : i + 200])
            query = f"SELECT ?item ?links WHERE {{ VALUES ?item {{ {values} }} ?item wikibase:sitelinks ?links }}"
            for row in self._get(WDQS_URL, {"query": query}).get("results", {}).get("bindings", []):
                counts[row["item"]["value"].rsplit("/", 1)[-1]] = int(row["links"]["value"])
        return counts


@dataclass(frozen=True)
class FamousPlace:
    qid: str
    label: str  # in English, what Google is searched for
    classes: str  # what Wikidata says it is, e.g. "minor basilica|Catholic cathedral"
    sitelink_count: int
    where: LatLng


def is_sight_class(classes: str) -> bool:
    """Whether an item's Wikidata classes ("arch bridge|stone bridge") make it a sight."""
    return bool(_SIGHT_CLASS.search(classes)) and not _NOT_SIGHT_CLASS.search(classes)


def _retry_after(resp: httpx.Response) -> float:
    try:
        return min(float(resp.headers.get("Retry-After", 0)), 120)
    except ValueError:  # an HTTP date instead of seconds: the growing wait covers it
        return 0


# ---------- matching ----------


def _best(
    place_name: str,
    category: str,
    entities: dict[str, Entity],
    distances: dict[str, float],
    via: str,
    place_is_area: bool,
) -> Match | None:
    best: Match | None = None
    for qid, entity in entities.items():
        if not entity.articles:
            continue  # nothing to describe it with
        if not place_is_area and describes_area(entity.description):
            continue
        score = max((name_score(place_name, name, entity.description, category) for name in entity.names), default=0.0)
        if score < MATCH_THRESHOLD:
            continue
        match = Match(qid, entity.articles, score, distances[qid], entity.sitelink_count, via)
        if best is None or match.rank() > best.rank():
            best = match
    return best


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
    match = None
    if found:
        match = _best(name, category, api.entities(list(found), languages), found, "search", is_area)
    # Unless the search found the place itself, right there, the items around it may do better.
    if match is None or match.score < 1 or match.distance_m > NEAR_M:
        near = api.nearby(where, radius_m)
        nearby_match = _best(name, category, api.entities(list(near), languages), near, "nearby", is_area)
        if nearby_match and (match is None or nearby_match.rank() > match.rank()):
            match = nearby_match
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

"""Give every place a Turkish name, and a description in both languages.

Names: places are stored under Google's English name. The Turkish one comes from
  1. the hand-entered list for the streets and districts added by hand (scripts/curated_pois.py);
  2. Wikidata: the Turkish label of the place's item (free): the name Turkish Wikipedia uses,
     e.g. Eiffel Tower -> Eyfel Kulesi, Hagia Sophia Grand Mosque -> Ayasofya;
  3. otherwise Google: the place's Turkish listing (Place Details, Pro SKU, 5,000 free a month),
     used only if Google really has a Turkish name (not the local one: no Japanese on a Turkish
     page).
  A name without a Turkish form stays as it is ("Musée d'Orsay").
Descriptions: a place with a Wikipedia article in one language only gets the other language's
  description machine-translated from it (Google Cloud Translation, 500,000 characters free a
  month), marked as a translation.

Everything is stored, so each place is paid for at most once: a run only visits places still
missing something, most popular first, and stops at its request and character budgets (the rest
waits for the next run). Without budgets only the free names are filled. --top keeps the Google
names to each city's most popular places, the ones plans are made of. After a 403 or 429 (an API
not enabled, a quota reached) a service isn't asked again in that run. The ingestion calls this
for every city it saves, with one small budget for the whole run, so new places are filled as
they arrive.

Usage (from the repo root):
    python -m scripts.localize_pois --dry-run           # what is missing, and what filling it costs
    python -m scripts.localize_pois --top 150 --max-name-requests 4500 --max-characters 450000
    python -m scripts.localize_pois --city paris --max-name-requests 300 --max-characters 50000
"""

import argparse
import re
import sys
from collections.abc import Callable, Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import POI, City
from app.services.places_client import PlacesAPIError, PlacesClient
from app.services.route_optimizer import REVIEWS_PER_SITELINK_SQUARED
from app.services.translate import TranslateClient, TranslateError
from app.services.wikipedia import WikiClient
from scripts.curated_pois import CURATED_NAMES_TR
from scripts.wikidata_overrides import PART, WRONG

CHUNK = 50  # places saved together, so an interrupted run keeps its progress
DESCRIPTION_MAX = 300  # the size of the description columns
STOP_STATUSES = {403, 429}  # not allowed, or over quota: asking again this run won't help
# One budget for a whole ingestion run (a monthly refresh does about ten cities): new places
# are filled as they come, and a month stays far inside the free tiers.
AUTO_NAME_REQUESTS = 300
AUTO_CHARACTERS = 60_000
AUTO_TOP = 150

GoogleName = tuple[str, str | None]  # (name, language code of that name)


class Labels(Protocol):
    def labels(self, qids: Sequence[str], lang: str) -> dict[str, str]: ...


class GoogleNames(Protocol):
    def display_name(self, place_id: str, language: str) -> GoogleName | None: ...


class Translator(Protocol):
    def translate(self, texts: Sequence[str], source: str, target: str) -> list[str]: ...


@dataclass
class Budget:
    """What a run may still spend; shared by the cities of one run."""

    name_requests: int
    characters: int
    top: int | None = None  # Google names only for each city's this many most popular places

    @classmethod
    def free(cls) -> "Budget":
        """Nothing to spend: only the hand-entered and Wikidata names."""
        return cls(name_requests=0, characters=0)


@dataclass
class Report:
    names_from_wikidata: int = 0
    names_from_google: int = 0  # asked Google, Turkish name or not (each is paid for once)
    names_kept: int = 0  # hand-added places: their hand-entered Turkish name, or their own name
    names_left: int = 0  # still missing: over budget, Google failed, or a dry run
    names_skipped: int = 0  # below the --top most popular places: left for a later run
    translated: int = 0
    translations_left: int = 0  # still missing: over budget, the translation failed, or a dry run
    characters: int = 0  # sent for translation and translated
    characters_needed: int = 0  # every one-language description's length, budget or not

    def add(self, other: "Report") -> None:
        for name in vars(self):
            setattr(self, name, getattr(self, name) + getattr(other, name))

    def summary(self) -> str:
        return (
            f"names: {self.names_from_wikidata} Wikidata, {self.names_from_google} Google, "
            f"{self.names_kept} kept, {self.names_left} left, {self.names_skipped} below --top; "
            f"descriptions: {self.translated} translated, {self.translations_left} left "
            f"({self.characters:,} characters sent, {self.characters_needed:,} needed in all)"
        )


def localize_city(
    db: Session,
    city_id: str,
    wiki: Labels,
    google: GoogleNames | None,
    translator: Translator | None,
    budget: Budget,
    dry_run: bool = False,
    log: Callable[[str], None] = print,
) -> Report:
    """Fill a city's missing Turkish names and one-language descriptions (see the module docstring).

    `google` and `translator` may be None (no API key): then only the free names are filled. A dry
    run asks Wikidata (free) but neither Google service, and writes nothing.
    """
    city = db.get(City, city_id)
    if city is None:
        raise ValueError(f"unknown city {city_id!r}")
    city_names = {n for n in (city.name, city.name_tr, city.id) if n}
    # Most popular first, as the planner counts it (Google reviews, or fame on Wikipedia where
    # that is more), so a budget or --top cut spends on the places plans are made of.
    popularity = func.greatest(
        func.coalesce(POI.user_rating_count, 0),
        REVIEWS_PER_SITELINK_SQUARED * func.power(func.coalesce(POI.wikidata_sitelinks, 0), 2),
    )
    rows = db.execute(
        select(
            POI.id,
            POI.place_id,
            POI.name,
            POI.name_tr,
            POI.wikidata_id,
            POI.description_tr,
            POI.description_en,
        )
        .where(POI.city_id == city_id)
        .order_by(popularity.desc(), POI.name)
    ).all()
    db.commit()  # don't keep a transaction open while waiting on the APIs

    def save_names(names: dict[str, str]) -> None:
        _save(db, [(poi_id, {"name_tr": name}) for poi_id, name in names.items()])

    report = Report()
    turkish_names(
        rows,
        city_names,
        wiki,
        None if dry_run else google,
        budget,
        report,
        save=None if dry_run else save_names,
        log=log,
    )
    translate_descriptions(db, rows, None if dry_run else translator, budget, report, log)
    return report


def turkish_names(
    rows: Sequence[Any],
    city_names: set[str],
    wiki: Labels,
    google: GoogleNames | None,
    budget: Budget,
    report: Report,
    save: Callable[[dict[str, str]], None] | None = None,
    log: Callable[[str], None] = print,
) -> dict[str, str]:
    """Turkish names for the rows that have none yet: {POI id: name}. `save` stores them as they
    come (every CHUNK Google answers, and at the end); without it nothing is stored."""
    missing = [r for r in rows if r.name_tr is None]
    # The item's label doesn't name these places: second listings of it, parts of it, wrong items.
    second = second_listings(rows) | {r.id for r in rows if r.place_id in PART or r.place_id in WRONG}
    rank = {row.id: i for i, row in enumerate(rows)}  # rows come most popular first
    found: dict[str, str] = {}
    unsaved: dict[str, str] = {}

    def keep(row: Any, name: str) -> None:
        found[row.id] = unsaved[row.id] = name

    def flush() -> None:
        if save and unsaved:
            save(dict(unsaved))
        unsaved.clear()

    # The item's label names a second listing's main place, not this part of it, so those don't ask.
    asks_wikidata = [r for r in missing if r.wikidata_id and r.id not in second]
    labels = wiki.labels(sorted({r.wikidata_id for r in asks_wikidata}), "tr") if asks_wikidata else {}
    label_of = {r.id: tidy_label(labels[r.wikidata_id], city_names) for r in asks_wikidata if r.wikidata_id in labels}

    for row in missing:
        if row.place_id in CURATED_NAMES_TR:
            keep(row, CURATED_NAMES_TR[row.place_id])
            report.names_kept += 1
        elif row.id in label_of:
            keep(row, label_of[row.id])
            report.names_from_wikidata += 1
        elif row.place_id.startswith("curated:"):  # no Google listing to ask
            keep(row, row.name)
            report.names_kept += 1

    asked = 0
    for row in missing:
        if row.id in found:
            continue
        if budget.top is not None and rank[row.id] >= budget.top:
            report.names_skipped += 1
            continue
        if google is None or budget.name_requests <= 0:
            report.names_left += 1
            continue
        budget.name_requests -= 1
        try:
            answer = google.display_name(row.place_id, "tr")
        except (httpx.HTTPError, PlacesAPIError) as e:
            status = e.status_code if isinstance(e, PlacesAPIError) else None
            if status != 404:  # anything but "no such place" is tried again next run
                log(f"  {row.name}: Google failed: {e}")
                if status in STOP_STATUSES:
                    log("  no more Google names this run")
                    budget.name_requests = 0
                report.names_left += 1
                continue
            answer = None  # gone from Google: the next refresh removes it, so don't ask again
        report.names_from_google += 1
        name, language = answer or (None, None)
        # Google has no Turkish name (it answers with the local one): the place's own name.
        keep(row, name if name and language == "tr" else row.name)
        asked += 1
        if asked % CHUNK == 0:
            flush()
    flush()
    return found


def second_listings(rows: Sequence[Any]) -> set[str]:
    """Places that share their Wikidata item with a more popular place of the city (rows come
    most popular first). The item's label names the main listing ("Topkapı Sarayı"), not this
    part of it ("Topkapı Palace Harem Units"), so these ask Google instead."""
    main: dict[str, str] = {}
    for row in rows:
        if row.wikidata_id:
            main.setdefault(row.wikidata_id, row.id)
    return {row.id for row in rows if row.wikidata_id and main[row.wikidata_id] != row.id}


def tidy_label(label: str, city_names: set[str] = frozenset()) -> str:
    """A Wikidata label as a place name: without the city that Turkish Wikipedia titles add to
    tell places apart ("Saint-Eustache, Paris", "Ulusal Doğa Tarihi Müzesi (Paris)"), and
    capitalized (labels of common nouns may start in lower case)."""
    name = label.strip()
    cities = {c.casefold() for c in city_names}
    bracket = re.fullmatch(r"(.+?)\s*\(([^()]*)\)", name)
    if bracket and bracket.group(2).strip().casefold() in cities:
        name = bracket.group(1)
    head, _, tail = name.rpartition(",")
    if head.strip() and tail.strip().casefold() in cities:
        name = head
    name = name.strip() or label.strip()
    if name[:1].islower():
        first = {"i": "İ", "ı": "I"}.get(name[0], name[0].upper())  # Turkish dotted and dotless i
        name = first + name[1:]
    return name


def translate_descriptions(
    db: Session,
    rows: Sequence[Any],
    translator: Translator | None,
    budget: Budget,
    report: Report,
    log: Callable[[str], None] = print,
) -> None:
    """Translate the description of places that have one in a single language into the other."""
    planned: list[tuple[str, str, str, str]] = []  # (POI id, from, into, text)
    for row in rows:
        if bool(row.description_tr) == bool(row.description_en):
            continue  # both from Wikipedia, or nothing to translate from
        source, target = ("en", "tr") if row.description_en else ("tr", "en")
        text = row.description_en or row.description_tr
        report.characters_needed += len(text)
        if len(text) > budget.characters:
            report.translations_left += 1
            continue
        budget.characters -= len(text)  # reserved, and given back if it isn't translated after all
        planned.append((row.id, source, target, text))

    if translator is None:
        report.translations_left += len(planned)
        budget.characters += sum(len(p[3]) for p in planned)
        return
    done = 0
    for source, target in (("en", "tr"), ("tr", "en")):
        items = [p for p in planned if p[1] == source]
        for start in range(0, len(items), CHUNK):
            chunk = items[start : start + CHUNK]
            try:
                texts = translator.translate([p[3] for p in chunk], source, target)
            except TranslateError as e:
                # Not allowed, over quota or down: the rest of the run would fail the same way.
                log(f"  translating failed, no more translations this run: {e}")
                report.translations_left += len(planned) - done
                budget.characters = 0
                return
            _save(
                db,
                [
                    (poi_id, {f"description_{target}": fit(text, DESCRIPTION_MAX), "description_translated": target})
                    for (poi_id, *_), text in zip(chunk, texts, strict=True)
                ],
            )
            done += len(chunk)
            report.translated += len(chunk)
            report.characters += sum(len(p[3]) for p in chunk)


def fit(text: str, limit: int) -> str:
    """The text, cut at a word and ended with "…" if it is longer than `limit`."""
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    if " " in cut:
        cut = cut[: cut.rindex(" ")]
    return cut.rstrip(" ,;:") + "…"


def _save(db: Session, changes: Sequence[tuple[str, dict[str, str]]]) -> None:
    for start in range(0, len(changes), CHUNK):
        for poi_id, values in changes[start : start + CHUNK]:
            db.execute(update(POI).where(POI.id == poi_id).values(**values))
        db.commit()


def localize_new_places(city_id: str, budget: Budget) -> None:
    """For the ingestion: fill a city's new places within the run's budget, without failing the
    run over these services."""
    api_key = get_settings().google_places_api_key
    try:
        with ExitStack() as stack:
            db = stack.enter_context(SessionLocal())
            wiki = stack.enter_context(WikiClient())
            google = stack.enter_context(PlacesClient(api_key)) if api_key and budget.name_requests else None
            translator = stack.enter_context(TranslateClient(api_key)) if api_key and budget.characters else None
            report = localize_city(db, city_id, wiki, google, translator, budget)
        print(f"  {report.summary()}")
    except Exception as e:  # the places are saved either way; the next run retries
        print(f"  Turkish names / translations failed, will retry next run: {e}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--city", action="append", help="city id (repeatable); default: every city")
    parser.add_argument("--dry-run", action="store_true", help="count what is missing and what it costs; write nothing")
    parser.add_argument(
        "--max-name-requests", type=int, default=0, help="Google Place Details requests for Turkish names (default 0)"
    )
    parser.add_argument("--max-characters", type=int, default=0, help="characters sent for translation (default 0)")
    parser.add_argument("--top", type=int, help="Google names only for each city's N most popular places")
    args = parser.parse_args()
    sys.stdout.reconfigure(errors="replace")  # place names in any script, on any console
    api_key = get_settings().google_places_api_key
    budget = Budget(name_requests=args.max_name_requests, characters=args.max_characters, top=args.top)

    total = Report()
    with ExitStack() as stack:
        db = stack.enter_context(SessionLocal())
        wiki = stack.enter_context(WikiClient())
        google = stack.enter_context(PlacesClient(api_key)) if api_key else None
        translator = stack.enter_context(TranslateClient(api_key)) if api_key else None
        city_ids = args.city or list(db.scalars(select(City.id).order_by(City.id)))
        for city_id in city_ids:
            print(f"== {city_id}")
            try:
                report = localize_city(db, city_id, wiki, google, translator, budget, dry_run=args.dry_run)
            except Exception as e:  # e.g. Wikidata down: what was saved stays, the other cities go ahead
                db.rollback()
                print(f"  skipped: {e}")
                continue
            print(f"  {report.summary()}")
            total.add(report)
        print(f"total {total.summary()}")
        if google is not None:
            print(f"Google name requests: {google.requests['names']}")
        if translator is not None:
            print(f"characters translated: {translator.characters:,}")


if __name__ == "__main__":
    main()

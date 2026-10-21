"""Give places a short description from Wikipedia (how they are matched: app/services/wikipedia.py).

Only places that were never looked up are visited, so a re-run is cheap; the ingestion calls this
for every city it saves, which describes new places as they arrive. Wikipedia and Wikidata need no
key and cost nothing, but they are asked one request at a time: about a second per place.

Usage (from the repo root):
    python -m scripts.describe_pois                 # every place not looked up yet
    python -m scripts.describe_pois --city paris    # one city (repeatable)
    python -m scripts.describe_pois --again         # look every place up again
    python -m scripts.describe_pois --dry-run       # print the matches, write nothing
    python -m scripts.describe_pois --sitelinks     # only the sitelink counts of earlier matches
"""

import argparse
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models import POI, City
from app.services.geo import LatLng
from app.services.wikipedia import COUNTRY_LANGUAGE, Match, WikiApi, WikiClient, WikiError, describe, match_place
from scripts.wikidata_overrides import PART, WRONG

CHUNK = 25  # places matched and saved together, so an interrupted run keeps its progress


@dataclass(frozen=True)
class Place:
    id: str
    place_id: str
    name: str
    where: LatLng
    category: str
    is_area: bool  # a hand-added district or street (place_id "curated:...")
    qid: str | None  # the Wikidata item it was matched to before, if any
    texts: dict[str, str | None]  # the descriptions stored now, by language
    translated: str | None  # which of them is a machine translation (scripts/localize_pois.py)


def describe_city(
    db: Session,
    city_id: str,
    api: WikiApi,
    again: bool = False,
    dry_run: bool = False,
    log: Callable[[str], None] = print,
) -> tuple[int, int]:
    """Look up a city's places; returns (places looked up, places described)."""
    city = db.get(City, city_id)
    if city is None:
        raise ValueError(f"unknown city {city_id!r}")
    local_language = COUNTRY_LANGUAGE.get(city.country_code or "", "en")
    query = select(
        POI.id,
        POI.place_id,
        POI.name,
        POI.latitude,
        POI.longitude,
        POI.category,
        POI.wikidata_id,
        POI.description_tr,
        POI.description_en,
        POI.description_translated,
    ).where(POI.city_id == city_id)
    if not again:
        query = query.where(POI.wiki_checked_at.is_(None))
    # Popular places first: if a run is cut short, the places people see most are done.
    query = query.order_by(POI.user_rating_count.desc().nulls_last(), POI.name)
    places = [
        Place(
            r.id,
            r.place_id,
            r.name,
            LatLng(r.latitude, r.longitude),
            r.category,
            r.place_id.startswith("curated:"),
            r.wikidata_id,
            {"tr": r.description_tr, "en": r.description_en},
            r.description_translated,
        )
        for r in db.execute(query)
    ]
    db.commit()  # don't keep a transaction open while waiting on Wikipedia

    described = 0
    for start in range(0, len(places), CHUNK):
        chunk = places[start : start + CHUNK]
        # A place whose lookup fails stays unchecked, so the next run tries it again.
        matches: dict[str, Match | None] = {}
        for place in chunk:
            if place.place_id in WRONG:  # checked by hand: no item fits (scripts/wikidata_overrides.py)
                matches[place.id] = None
                continue
            try:
                matches[place.id] = match_place(
                    api, place.name, place.where, place.category, local_language, place.is_area
                )
            except WikiError as e:
                log(f"  {place.name}: {e}")
        try:
            texts = describe(api, [m for m in matches.values() if m])
        except WikiError as e:
            log(f"  descriptions for this batch failed: {e}")
            continue
        checked_at = datetime.now(UTC)
        for place in chunk:
            if place.id not in matches:
                continue
            match = matches[place.id]
            text = texts.get(match.qid, {}) if match else {}
            if text:
                described += 1
            if dry_run:
                found = f"{match.qid} {match.articles.get('en') or match.articles.get('tr')}" if match else "-"
                log(f"  {place.name} -> {found}: {text.get('tr') or text.get('en') or ''}")
            else:
                qid = match.qid if match else None
                stored, translated = keep_translation(place, text)
                # A Turkish name taken from another item's label is looked up again.
                renamed = {"name_tr": None} if qid != place.qid else {}
                db.execute(
                    update(POI)
                    .where(POI.id == place.id)
                    .values(
                        wikidata_id=qid,
                        # Part of a larger whole: the whole's fame isn't the place's own.
                        wikidata_sitelinks=match.sitelink_count if match and place.place_id not in PART else None,
                        description_tr=stored["tr"],
                        description_en=stored["en"],
                        description_translated=translated,
                        wiki_checked_at=checked_at,
                        **renamed,
                    )
                )
        if not dry_run:
            db.commit()
    return len(places), described


def keep_translation(place: Place, fresh: dict[str, str]) -> tuple[dict[str, str | None], str | None]:
    """The descriptions to store, and which is a machine translation: fresh Wikipedia texts, but a
    stored translation stays while Wikipedia still has no article in its language and the text
    it was translated from is unchanged (so it isn't paid for again)."""
    texts: dict[str, str | None] = {"tr": fresh.get("tr"), "en": fresh.get("en")}
    lang = place.translated
    if lang in texts and texts[lang] is None:
        source = "en" if lang == "tr" else "tr"
        if texts[source] and texts[source] == place.texts[source]:
            texts[lang] = place.texts[lang]
            return texts, lang
    return texts, None


def fill_sitelinks(db: Session, api: WikiClient, city_id: str | None = None) -> int:
    """Store the sitelink counts of places matched before the counts were kept (one Wikidata
    query per 200 places); returns how many places were updated."""
    query = select(POI.id, POI.wikidata_id).where(POI.wikidata_id.is_not(None), POI.wikidata_sitelinks.is_(None))
    if city_id:
        query = query.where(POI.city_id == city_id)
    rows = db.execute(query).all()
    db.commit()
    counts = api.sitelink_counts(sorted({row.wikidata_id for row in rows}))
    updated = 0
    for row in rows:
        if row.wikidata_id in counts:
            db.execute(update(POI).where(POI.id == row.id).values(wikidata_sitelinks=counts[row.wikidata_id]))
            updated += 1
    db.commit()
    return updated


def describe_new_places(city_id: str) -> None:
    """For the ingestion: describe a city's new places, without failing the run over Wikipedia."""
    try:
        with SessionLocal() as db, WikiClient() as api:
            looked_up, described = describe_city(db, city_id, api, log=lambda _: None)
        print(f"  descriptions: {described} of {looked_up} new places")
    except Exception as e:  # the places are saved either way; the next run retries
        print(f"  descriptions failed, will retry next run: {e}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--city", action="append", help="city id (repeatable); default: every city")
    parser.add_argument("--again", action="store_true", help="look up places that were looked up before too")
    parser.add_argument("--dry-run", action="store_true", help="print the matches, write nothing")
    parser.add_argument(
        "--sitelinks",
        action="store_true",
        help="only store the sitelink counts of places matched before they were kept",
    )
    args = parser.parse_args()
    sys.stdout.reconfigure(errors="replace")  # place names in any script, on any console

    if args.sitelinks:
        with SessionLocal() as db, WikiClient() as api:
            for city_id in args.city or [None]:
                print(f"sitelink counts stored for {fill_sitelinks(db, api, city_id)} places")
        return

    with SessionLocal() as db, WikiClient() as api:
        city_ids = args.city or list(db.scalars(select(City.id).order_by(City.id)))
        for city_id in city_ids:
            print(f"== {city_id}")
            looked_up, described = describe_city(db, city_id, api, again=args.again, dry_run=args.dry_run)
            print(f"  described {described} of {looked_up} places")
        print(f"requests: {api.requests}")


if __name__ == "__main__":
    main()

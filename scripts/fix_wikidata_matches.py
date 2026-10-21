"""Apply scripts/wikidata_overrides.py to the places already in the database.

- WRONG places lose their item: wikidata_id, fame (sitelinks), descriptions with their
  translation mark, and the Turkish name, which may have been the item's label.
- PART places keep the item and its description, but lose its fame and the Turkish name taken
  from its label.

Only places that still carry what the override takes away are changed, so a second run does
nothing. The Turkish names are filled again by scripts/localize_pois.py: with --localize right
away (Google names for these places, within --max-name-requests), otherwise by the next ingestion.

Usage (from the repo root):
    python -m scripts.fix_wikidata_matches --dry-run
    python -m scripts.fix_wikidata_matches --localize --max-name-requests 300
"""

import argparse
import sys
from contextlib import ExitStack

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import POI
from app.services.places_client import PlacesClient
from app.services.wikipedia import WikiClient
from scripts.localize_pois import Budget, localize_city
from scripts.wikidata_overrides import PART, WRONG


def fix_matches(db: Session, dry_run: bool = False) -> tuple[set[str], set[str]]:
    """Unmatch the WRONG places and take the fame and label off the PART ones still carrying them.

    Returns the cities of the changed places and the names of what changed (for the log)."""
    wrong = db.execute(
        select(POI.id, POI.city_id, POI.name).where(POI.place_id.in_(WRONG), POI.wikidata_id.is_not(None))
    ).all()
    part = db.execute(
        select(POI.id, POI.city_id, POI.name).where(POI.place_id.in_(PART), POI.wikidata_sitelinks.is_not(None))
    ).all()
    if not dry_run:
        for row in wrong:
            db.execute(
                update(POI)
                .where(POI.id == row.id)
                .values(
                    wikidata_id=None,
                    wikidata_sitelinks=None,
                    description_tr=None,
                    description_en=None,
                    description_translated=None,
                    name_tr=None,
                )
            )
        for row in part:
            db.execute(update(POI).where(POI.id == row.id).values(wikidata_sitelinks=None, name_tr=None))
        db.commit()
    changed = [f"wrong: {r.city_id}: {r.name}" for r in wrong] + [f"part: {r.city_id}: {r.name}" for r in part]
    return {r.city_id for r in [*wrong, *part]}, set(changed)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="list what would change; write nothing")
    parser.add_argument("--localize", action="store_true", help="fill the cleared Turkish names right away")
    parser.add_argument("--max-name-requests", type=int, default=300, help="Google names for --localize (default 300)")
    args = parser.parse_args()
    sys.stdout.reconfigure(errors="replace")

    with SessionLocal() as db:
        cities, changed = fix_matches(db, dry_run=args.dry_run)
        for line in sorted(changed):
            print(f"  {line}")
        print(f"{'would change' if args.dry_run else 'changed'} {len(changed)} places in {len(cities)} cities")
        if args.dry_run or not args.localize:
            return
        api_key = get_settings().google_places_api_key
        budget = Budget(name_requests=args.max_name_requests, characters=0)
        with ExitStack() as stack:
            wiki = stack.enter_context(WikiClient())
            google = stack.enter_context(PlacesClient(api_key)) if api_key else None
            for city_id in sorted(cities):
                report = localize_city(db, city_id, wiki, google, None, budget)
                print(f"== {city_id}: {report.summary()}")


if __name__ == "__main__":
    main()

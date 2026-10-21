"""Plans shared by link: noloroute.com/p/<id> opens a frozen copy of the plan for anyone, no login.

The link page is the web app's index.html with the plan's title and stops in its preview tags,
so messaging apps (WhatsApp, Telegram, ...) show what the link is about.

A shared plan is shown to anyone under noloroute.com, so what it says about places comes from the
database, not from the sharer (see trusted_copy).
"""

import hashlib
import json
import re
import secrets
import string
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from html import escape
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import DbSession
from app.api.v1.routes_route import plan_totals, validated_city, with_current_texts
from app.core.rate_limit import RateLimiter, limit_by_ip, too_many_requests
from app.models import POI, City, SharedPlan
from app.schemas.route import LegDetails, RoutePlanResponse
from app.schemas.share import SharedPlanOut, ShareOut, ShareRequest
from app.services.opening_hours import hours_on
from app.services.route_optimizer import stop_warning

router = APIRouter(prefix="/shares", tags=["shares"])
# The link page itself, outside /api/v1.
page_router = APIRouter(include_in_schema=False)

SHARES_PER_IP = RateLimiter(limit=30, window_seconds=60 * 60)
# All visitors together: bounds what the database can grow by in a day, whoever sends the requests.
MAX_SHARES_PER_DAY = 1000
# A 7-day transit plan with street paths for every leg is far smaller.
MAX_SHARED_PLAN_BYTES = 500_000
# Transit rides keep Google's line and stop names (nothing to check them against), cut to this.
MAX_RIDE_TEXT = 80
HEX_COLOR = re.compile(r"#[0-9A-Fa-f]{6}")

# 62^8 ≈ 2·10^14 links: not guessable, and short enough to read out.
SHARE_ID_ALPHABET = string.ascii_letters + string.digits
SHARE_ID_LENGTH = 8
SHARE_ID = re.compile(rf"[{re.escape(SHARE_ID_ALPHABET)}]{{{SHARE_ID_LENGTH}}}")
# Stops named in the link preview; the rest are counted.
PREVIEW_STOPS = 4


def new_share_id() -> str:
    return "".join(secrets.choice(SHARE_ID_ALPHABET) for _ in range(SHARE_ID_LENGTH))


@router.post(
    "",
    response_model=ShareOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(limit_by_ip(SHARES_PER_IP))],
)
def share_plan(req: ShareRequest, db: DbSession) -> ShareOut:
    """Store a copy of the plan and return its link. The same plan shared again keeps its link."""
    plan = trusted_copy(db, req.plan).model_dump(mode="json")
    content = json.dumps(plan, sort_keys=True, separators=(",", ":"))
    if len(content) > MAX_SHARED_PLAN_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "The plan is too large to share")
    digest = hashlib.sha256(f"{req.lang}:{content}".encode()).hexdigest()
    share = db.scalar(select(SharedPlan).where(SharedPlan.content_hash == digest))
    if share is None:
        since = datetime.now(UTC) - timedelta(days=1)
        if db.scalar(select(func.count()).where(SharedPlan.created_at > since)) >= MAX_SHARES_PER_DAY:
            raise too_many_requests(60 * 60)
        share = SharedPlan(id=new_share_id(), city_id=req.plan.city_id, lang=req.lang, content_hash=digest, plan=plan)
        db.add(share)
        try:
            db.commit()
        except IntegrityError:  # shared at the same moment by another request
            db.rollback()
            share = db.scalar(select(SharedPlan).where(SharedPlan.content_hash == digest))
            if share is None:
                raise
    return ShareOut(id=share.id, path=f"/p/{share.id}")


@router.get("/{share_id}", response_model=SharedPlanOut)
def get_shared_plan(share_id: str, db: DbSession) -> SharedPlanOut:
    share = _find(db, share_id)
    if share is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Shared plan not found")
    return SharedPlanOut(id=share.id, created_at=share.created_at, plan=_current_plan(db, share))


# HEAD too: some link previewers ask that first.
@page_router.api_route("/p/{share_id}", methods=["GET", "HEAD"], response_class=HTMLResponse)
def shared_plan_page(share_id: str, request: Request, db: DbSession) -> HTMLResponse:
    """The web app, with the plan in the link preview tags. An unknown link still gets the app
    (it says the link was not found), with a 404 status."""
    html = _index_html(request.app.state.frontend_index)
    if html is None:  # no built frontend: in development Vite serves the app
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    headers = {
        # Like index.html: browsers must check it on every visit, or they keep last week's bundle.
        "Cache-Control": "no-cache",
        # A link posted in public must not turn up in search results: it shows where someone stays.
        "X-Robots-Tag": "noindex",
    }
    share = _find(db, share_id)
    if share is None:
        return HTMLResponse(html, status_code=status.HTTP_404_NOT_FOUND, headers=headers)
    plan = _current_plan(db, share)
    title, description = link_preview(plan, db.get_one(City, share.city_id), share.lang)
    url = str(request.url_for("shared_plan_page", share_id=share.id))  # without tracking parameters
    page = with_preview(html, share.lang, title, description, url=url)
    return HTMLResponse(page, headers=headers)


def trusted_copy(db: Session, plan: RoutePlanResponse) -> RoutePlanResponse:
    """The plan with what a sharer could make up replaced by what the database says.

    Places' names, categories, positions, prices, ratings and opening hours come from their rows,
    the currency and price notes from the city, and the totals are counted again; dropped stops
    must be places of the city. Times, distances and street paths stay as planned (numbers and map
    lines). Transit rides keep Google's line and stop names, cut short, and only real colour codes.
    """
    city = validated_city(db, plan)
    poi_ids = {stop.poi_id for day in plan.days for stop in day.stops}
    pois = {poi.id: poi for poi in db.scalars(select(POI).where(POI.city_id == city.id, POI.id.in_(poi_ids)))}
    dropped = {name for day in plan.days for name in day.dropped_stops}
    places = set(db.scalars(select(POI.name).where(POI.city_id == city.id, POI.name.in_(dropped))))
    days = []
    for day in plan.days:
        stops = []
        for stop in day.stops:
            poi = pois[stop.poi_id]
            stops.append(
                stop.model_copy(
                    update={
                        "name": poi.name,
                        "name_tr": poi.name_tr,
                        "category": poi.category,
                        "latitude": poi.latitude,
                        "longitude": poi.longitude,
                        "visit_minutes": poi.avg_duration_min,
                        "entry_price": poi.entry_price,
                        "rating": poi.rating,
                        "hours": hours_on(poi.opening_hours, day.date) if day.date else None,
                        "warning": stop_warning(poi, day.date, day.weather),
                        "leg_from_previous": _trusted_leg(stop.leg_from_previous),
                    }
                )
            )
        update = {
            "stops": stops,
            "return_leg": _trusted_leg(day.return_leg),
            "total_visit_minutes": sum(stop.visit_minutes for stop in stops),
            "dropped_stops": [name for name in day.dropped_stops if name in places],
            "dropped_stops_tr": [],  # looked up from the names when the plan is opened
        }
        days.append(day.model_copy(update=update))
    return plan.model_copy(
        update={
            "days": days,
            "currency_code": city.currency_code,
            "price_basis": city.price_basis,
            "prices_checked_on": city.prices_checked_on,
            **plan_totals(days),
        }
    )


def _trusted_leg(leg: LegDetails | None) -> LegDetails | None:
    if leg is None:
        return None

    def text(value: str | None) -> str | None:
        return value[:MAX_RIDE_TEXT] if value else value

    def color(value: str | None) -> str | None:
        return value if value and HEX_COLOR.fullmatch(value) else None

    rides = [
        ride.model_copy(
            update={
                "vehicle": text(ride.vehicle),
                "line": text(ride.line),
                "headsign": text(ride.headsign),
                "from_stop": text(ride.from_stop),
                "to_stop": text(ride.to_stop),
                "agency": text(ride.agency),
                "line_color": color(ride.line_color),
                "line_text_color": color(ride.line_text_color),
            }
        )
        for ride in leg.rides
    ]
    return leg.model_copy(update={"rides": rides})


def link_preview(plan: RoutePlanResponse, city: City, lang: str) -> tuple[str, str]:
    """The link preview's title and description, e.g. "Paris · 2-day trip plan" and
    "9 stops: Eiffel Tower, Louvre Museum, ... and 5 more."."""
    turkish = lang == "tr"
    city_name = (city.name_tr or city.name) if turkish else city.name
    stops = [stop for day in plan.days for stop in day.stops]
    named = [(stop.name_tr or stop.name) if turkish else stop.name for stop in stops[:PREVIEW_STOPS]]
    rest = len(stops) - len(named)
    if turkish:
        title = f"{city_name} · {plan.duration_days} günlük gezi planı"
        description = f"{len(stops)} durak: {', '.join(named)}" + (f" ve {rest} durak daha." if rest else ".")
    else:
        title = f"{city_name} · {plan.duration_days}-day trip plan"
        count = f"{len(stops)} stop{'' if len(stops) == 1 else 's'}"
        description = f"{count}: {', '.join(named)}" + (f" and {rest} more." if rest else ".")
    return title, description


def with_preview(html: str, lang: str, title: str, description: str, url: str) -> str:
    """index.html with the page language, title and preview tags (description, og:*) replaced."""
    html = re.sub(r'<html lang="[^"]*"', lambda _: f'<html lang="{lang}"', html, count=1)
    html = re.sub(r"<title>[^<]*</title>", lambda _: f"<title>{escape(title)} · NoloRoute</title>", html, count=1)
    for key, value in (
        ("description", description),
        ("og:title", title),
        ("og:description", description),
        ("og:url", url),
    ):
        pattern = rf'(<meta (?:name|property)="{re.escape(key)}" content=")[^"]*(")'
        html = re.sub(pattern, lambda m, v=value: m.group(1) + escape(v) + m.group(2), html, count=1)
    return html


def _index_html(path: Path) -> str | None:
    try:
        return _read_index_html(path, path.stat().st_mtime_ns)
    except FileNotFoundError:
        return None


@lru_cache(maxsize=4)
def _read_index_html(path: Path, modified: int) -> str:
    """Read once per version of the file: a new frontend build is picked up without a restart."""
    return path.read_text(encoding="utf-8")


def _find(db: Session, share_id: str) -> SharedPlan | None:
    return db.get(SharedPlan, share_id) if SHARE_ID.fullmatch(share_id) else None


def _current_plan(db: Session, share: SharedPlan) -> RoutePlanResponse:
    """The shared plan with its places' current names and descriptions (like a saved route)."""
    return with_current_texts(db, RoutePlanResponse.model_validate(share.plan))

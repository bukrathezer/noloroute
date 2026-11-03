"""The admin page: how many people use the app, and its accounts. Only for the addresses in
ADMIN_EMAILS (confirmed accounts); other accounts get 404. Left out of the API docs.

Read-only. Passwords aren't shown, nor could they be: only their hashes are stored.
"""

from datetime import UTC, datetime, time, timedelta
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import Date, cast, distinct, func, select

from app.api.deps import CurrentAdmin, DbSession
from app.models import City, PlanLog, SavedRoute, SharedPlan, User
from app.schemas.admin import AdminOverview, AdminUser, AdminUserPage, CityActivity, DayCount, UserCounts

router = APIRouter(prefix="/admin", tags=["admin"], include_in_schema=False)

TREND_DAYS = 30
TOP_CITIES = 10
MAX_USERS_PER_PAGE = 100


@router.get("/overview", response_model=AdminOverview)
def overview(_: CurrentAdmin, db: DbSession) -> AdminOverview:
    now = datetime.now(UTC)
    week = now - timedelta(days=7)
    # The last 30 days are whole (UTC) days, today the last of them: the same span as the charts.
    month = datetime.combine(now.date() - timedelta(days=TREND_DAYS - 1), time(), UTC)

    def count(query) -> int:
        return db.scalar(query) or 0

    users = UserCounts(
        total=count(select(func.count()).select_from(User)),
        verified=count(select(func.count()).where(User.email_verified_at.is_not(None))),
        with_google=count(select(func.count()).where(User.google_sub.is_not(None))),
        with_password=count(select(func.count()).where(User.hashed_password.is_not(None))),
        new_last_7_days=count(select(func.count()).where(User.created_at >= week)),
        new_last_30_days=count(select(func.count()).where(User.created_at >= month)),
    )

    def per_city(city_id, *where) -> dict[str, int]:
        return dict(db.execute(select(city_id, func.count()).where(*where).group_by(city_id)).all())

    # Per city, over the last 30 days for plans and all time for saved and shared ones.
    plans_by_city = per_city(PlanLog.city_id, PlanLog.created_at >= month)
    saved_by_city = per_city(SavedRoute.city_id)
    shared_by_city = per_city(SharedPlan.city_id)
    city_ids = set(plans_by_city) | set(saved_by_city) | set(shared_by_city)
    cities = {c.id: c for c in db.scalars(select(City).where(City.id.in_(city_ids)))} if city_ids else {}
    ranked = sorted(
        city_ids,
        key=lambda c: (plans_by_city.get(c, 0), saved_by_city.get(c, 0), shared_by_city.get(c, 0)),
        reverse=True,
    )[:TOP_CITIES]

    return AdminOverview(
        users=users,
        signups_by_day=_by_day(db, User.created_at, month),
        plans_total=count(select(func.count()).select_from(PlanLog)),
        plans_last_7_days=count(select(func.count()).where(PlanLog.created_at >= week)),
        plans_last_30_days=count(select(func.count()).where(PlanLog.created_at >= month)),
        plans_by_day=_by_day(db, PlanLog.created_at, month),
        saved_routes=count(select(func.count()).select_from(SavedRoute)),
        users_with_saved_routes=count(select(func.count(distinct(SavedRoute.user_id)))),
        shared_plans=count(select(func.count()).select_from(SharedPlan)),
        shared_plans_last_7_days=count(select(func.count()).where(SharedPlan.created_at >= week)),
        top_cities=[
            CityActivity(
                city_id=c,
                name=cities[c].name if c in cities else c,
                name_tr=cities[c].name_tr if c in cities else None,
                plans_last_30_days=plans_by_city.get(c, 0),
                saved_routes=saved_by_city.get(c, 0),
                shared_plans=shared_by_city.get(c, 0),
            )
            for c in ranked
        ],
    )


def _by_day(db: DbSession, column, since: datetime) -> list[DayCount]:
    """Rows per UTC day from `since` (a UTC midnight) to today, every day listed, oldest first."""
    day = cast(func.timezone("UTC", column), Date)  # not the database session's time zone
    counts = dict(db.execute(select(day, func.count()).where(column >= since).group_by(day)).all())
    days = [since.date() + timedelta(days=i) for i in range((datetime.now(UTC).date() - since.date()).days + 1)]
    return [DayCount(day=d, count=counts.get(d, 0)) for d in days]


@router.get("/users", response_model=AdminUserPage)
def users(
    _: CurrentAdmin,
    db: DbSession,
    q: Annotated[str, Query(max_length=200, description="Part of an email address.")] = "",
    limit: Annotated[int, Query(ge=1, le=MAX_USERS_PER_PAGE)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AdminUserPage:
    """Accounts, newest first, with their saved-route counts."""
    search = q.strip().lower()
    where = [User.email.contains(search, autoescape=True)] if search else []
    total = db.scalar(select(func.count()).select_from(User).where(*where)) or 0
    saved = select(SavedRoute.user_id, func.count().label("n")).group_by(SavedRoute.user_id).subquery()
    rows = db.execute(
        select(User, func.coalesce(saved.c.n, 0))
        .outerjoin(saved, saved.c.user_id == User.id)
        .where(*where)
        .order_by(User.created_at.desc(), User.id.desc())  # the id keeps pages apart on equal times
        .limit(limit)
        .offset(offset)
    ).all()
    return AdminUserPage(
        total=total,
        users=[
            AdminUser(
                id=u.id,
                email=u.email,
                created_at=u.created_at,
                verified=u.email_verified_at is not None,
                google=u.google_sub is not None,
                has_password=u.hashed_password is not None,
                saved_routes=n,
                last_login_at=u.last_login_at,
            )
            for u, n in rows
        ],
    )

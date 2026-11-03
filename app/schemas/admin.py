from datetime import date, datetime

from pydantic import BaseModel


class DayCount(BaseModel):
    day: date
    count: int


class UserCounts(BaseModel):
    total: int
    verified: int
    with_google: int
    with_password: int
    new_last_7_days: int
    new_last_30_days: int


class CityActivity(BaseModel):
    city_id: str
    name: str
    name_tr: str | None
    plans_last_30_days: int
    saved_routes: int
    shared_plans: int


class AdminOverview(BaseModel):
    users: UserCounts
    signups_by_day: list[DayCount]  # the last 30 UTC days, oldest first, days without any included
    plans_total: int
    plans_last_7_days: int
    plans_last_30_days: int
    plans_by_day: list[DayCount]
    saved_routes: int
    users_with_saved_routes: int
    shared_plans: int
    shared_plans_last_7_days: int
    top_cities: list[CityActivity]


class AdminUser(BaseModel):
    id: str
    email: str
    created_at: datetime
    verified: bool
    google: bool
    has_password: bool
    saved_routes: int
    last_login_at: datetime | None


class AdminUserPage(BaseModel):
    total: int  # matching the search
    users: list[AdminUser]

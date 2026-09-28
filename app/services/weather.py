"""Daily weather for the trip days, from Open-Meteo (free, no API key).

Dates up to FORECAST_DAYS ahead get a real forecast. Later dates get the "typical" weather: the
same calendar days over the past TYPICAL_YEARS years, averaged. Open-Meteo is free for
non-commercial use; a commercial launch needs their paid plan (or another provider behind this
same interface).
"""

import asyncio
import time
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Literal

import httpx

from app.services.geo import LatLng

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_DAYS = 16  # Open-Meteo's forecast horizon, today included
TYPICAL_YEARS = 5
RAINY_CHANCE = 60  # % precipitation probability from which a forecast day counts as rainy
RAINY_SUM_MM = 5.0
WET_DAY_MM = 1.0  # a past day with at least this much precipitation counts as a rainy one

FORECAST_TTL_S = 60 * 60
TYPICAL_TTL_S = 7 * 24 * 60 * 60

Condition = Literal["clear", "partly_cloudy", "cloudy", "fog", "drizzle", "rain", "snow", "thunderstorm"]
WET_CONDITIONS = {"rain", "snow", "thunderstorm"}


class WeatherError(Exception):
    pass


@dataclass(frozen=True)
class DayWeather:
    day: date
    source: Literal["forecast", "typical"]
    condition: Condition
    temp_max_c: float
    temp_min_c: float
    precipitation_chance: int | None  # percent
    is_rainy: bool


def condition_from_code(code: int) -> Condition:
    """WMO weather code (as used by Open-Meteo) to a small set of conditions."""
    if code == 0:
        return "clear"
    if code in (1, 2):
        return "partly_cloudy"
    if code == 3:
        return "cloudy"
    if code in (45, 48):
        return "fog"
    if 51 <= code <= 57:
        return "drizzle"
    if 61 <= code <= 67 or 80 <= code <= 82:
        return "rain"
    if 71 <= code <= 77 or code in (85, 86):
        return "snow"
    if code >= 95:
        return "thunderstorm"
    return "cloudy"


class WeatherClient:
    def __init__(self, timeout: float = 6.0, transport: httpx.AsyncBaseTransport | None = None) -> None:
        # `transport` lets tests answer requests without the network.
        self._http = httpx.AsyncClient(timeout=timeout, transport=transport)
        self._cache: dict[tuple[float, float, date, str], tuple[float, DayWeather]] = {}

    async def aclose(self) -> None:
        await self._http.aclose()

    async def for_dates(self, where: LatLng, days: list[date], today: date | None = None) -> list[DayWeather]:
        """Weather for each of `days`, in order. Raises WeatherError if Open-Meteo can't be reached."""
        today = today or date.today()
        horizon = today + timedelta(days=FORECAST_DAYS - 1)
        near = [d for d in days if d <= horizon]
        far = [d for d in days if d > horizon]
        forecast, typical = await asyncio.gather(self._forecast(where, near), self._typical(where, far))
        by_day = {w.day: w for w in (*forecast, *typical)}
        return [by_day[d] for d in days]

    async def _forecast(self, where: LatLng, days: list[date]) -> list[DayWeather]:
        if not days:
            return []
        cached = [self._cached(where, d, "forecast") for d in days]
        if all(cached):
            return cached  # type: ignore[return-value]
        data = await self._get(
            FORECAST_URL,
            where,
            min(days),
            max(days),
            "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum",
        )
        results = []
        for row in _rows(data):
            if row["day"] not in days:
                continue
            chance = row.get("precipitation_probability_max")
            condition = condition_from_code(int(row["weather_code"]))
            weather = DayWeather(
                day=row["day"],
                source="forecast",
                condition=condition,
                temp_max_c=round(row["temperature_2m_max"], 1),
                temp_min_c=round(row["temperature_2m_min"], 1),
                precipitation_chance=None if chance is None else int(chance),
                is_rainy=condition in WET_CONDITIONS
                or (chance or 0) >= RAINY_CHANCE
                or (row.get("precipitation_sum") or 0) >= RAINY_SUM_MM,
            )
            self._store(where, weather, FORECAST_TTL_S)
            results.append(weather)
        return results

    async def _typical(self, where: LatLng, days: list[date]) -> list[DayWeather]:
        if not days:
            return []
        cached = [self._cached(where, d, "typical") for d in days]
        if all(cached):
            return cached  # type: ignore[return-value]
        # Same calendar days in each of the past years, fetched concurrently.
        years = range(1, TYPICAL_YEARS + 1)
        responses = await asyncio.gather(
            *(
                self._get(
                    ARCHIVE_URL,
                    where,
                    _years_back(min(days), n),
                    _years_back(max(days), n),
                    "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum",
                )
                for n in years
            )
        )
        samples: dict[tuple[int, int], list[dict[str, Any]]] = {}
        for data in responses:
            for row in _rows(data):
                samples.setdefault((row["day"].month, row["day"].day), []).append(row)

        results = []
        for d in days:
            rows = [r for r in samples.get((d.month, d.day), []) if r.get("temperature_2m_max") is not None]
            if not rows:
                continue
            wet_share = sum((r.get("precipitation_sum") or 0) >= WET_DAY_MM for r in rows) / len(rows)
            weather = DayWeather(
                day=d,
                source="typical",
                condition=Counter(condition_from_code(int(r["weather_code"])) for r in rows).most_common(1)[0][0],
                temp_max_c=round(sum(r["temperature_2m_max"] for r in rows) / len(rows), 1),
                temp_min_c=round(sum(r["temperature_2m_min"] for r in rows) / len(rows), 1),
                precipitation_chance=round(wet_share * 100),
                is_rainy=wet_share >= 0.5,
            )
            self._store(where, weather, TYPICAL_TTL_S)
            results.append(weather)
        return results

    async def _get(self, url: str, where: LatLng, start: date, end: date, daily: str) -> dict[str, Any]:
        params = {
            "latitude": round(where.lat, 3),
            "longitude": round(where.lng, 3),
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "daily": daily,
            "timezone": "auto",
        }
        try:
            resp = await self._http.get(url, params=params)
        except httpx.HTTPError as exc:
            raise WeatherError(f"request failed: {exc}") from exc
        if resp.is_error:
            raise WeatherError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    def _cached(self, where: LatLng, day: date, source: str) -> DayWeather | None:
        entry = self._cache.get((round(where.lat, 2), round(where.lng, 2), day, source))
        return entry[1] if entry and entry[0] > time.monotonic() else None

    def _store(self, where: LatLng, weather: DayWeather, ttl: float) -> None:
        self._cache[(round(where.lat, 2), round(where.lng, 2), weather.day, weather.source)] = (
            time.monotonic() + ttl,
            weather,
        )


def _rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Open-Meteo returns column lists ({"time": [...], "weather_code": [...]}); turn them into rows."""
    daily = data.get("daily") or {}
    times = daily.get("time") or []
    return [
        {"day": date.fromisoformat(t), **{k: v[i] for k, v in daily.items() if k != "time"}}
        for i, t in enumerate(times)
    ]


def _years_back(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year - years)
    except ValueError:  # 29 February in a non-leap year
        return day.replace(year=day.year - years, day=28)

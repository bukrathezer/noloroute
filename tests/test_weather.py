import asyncio
from datetime import date, timedelta

import httpx
import pytest

from app.services.geo import LatLng
from app.services.weather import FORECAST_DAYS, WeatherClient, WeatherError, condition_from_code

PARIS = LatLng(48.8566, 2.3522)
TODAY = date(2026, 10, 1)


def daily(days: list[date], **columns: list) -> dict:
    return {"daily": {"time": [d.isoformat() for d in days], **columns}}


def test_condition_codes() -> None:
    assert [condition_from_code(c) for c in (0, 2, 3, 45, 53, 63, 81, 75, 95)] == [
        "clear",
        "partly_cloudy",
        "cloudy",
        "fog",
        "drizzle",
        "rain",
        "rain",
        "snow",
        "thunderstorm",
    ]


class FakeOpenMeteo:
    """Answers forecast and archive requests; archive days get rain in 3 of 5 past years."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail:
            return httpx.Response(500, text="down")
        start = date.fromisoformat(request.url.params["start_date"])
        end = date.fromisoformat(request.url.params["end_date"])
        days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
        if "archive" in request.url.host:
            wet = start.year in (TODAY.year - 1, TODAY.year - 2, TODAY.year - 3)
            return httpx.Response(
                200,
                json=daily(
                    days,
                    weather_code=[63 if wet else 1] * len(days),
                    temperature_2m_max=[20.0] * len(days),
                    temperature_2m_min=[10.0] * len(days),
                    precipitation_sum=[4.0 if wet else 0.0] * len(days),
                ),
            )
        return httpx.Response(
            200,
            json=daily(
                days,
                weather_code=[61, 1][: len(days)] + [0] * max(0, len(days) - 2),
                temperature_2m_max=[18.24] * len(days),
                temperature_2m_min=[11.0] * len(days),
                precipitation_probability_max=[80, 10][: len(days)] + [0] * max(0, len(days) - 2),
                precipitation_sum=[6.0, 0.0][: len(days)] + [0.0] * max(0, len(days) - 2),
            ),
        )


def client_for(fake: FakeOpenMeteo) -> WeatherClient:
    return WeatherClient(transport=httpx.MockTransport(fake))


def test_near_dates_use_the_forecast() -> None:
    fake = FakeOpenMeteo()
    days = [TODAY + timedelta(days=1), TODAY + timedelta(days=2)]
    result = asyncio.run(client_for(fake).for_dates(PARIS, days, today=TODAY))
    assert [w.source for w in result] == ["forecast", "forecast"]
    rainy, dry = result
    assert (rainy.condition, rainy.precipitation_chance, rainy.is_rainy) == ("rain", 80, True)
    assert (dry.condition, dry.precipitation_chance, dry.is_rainy) == ("partly_cloudy", 10, False)
    assert rainy.temp_max_c == 18.2
    assert len(fake.requests) == 1


def test_far_dates_use_past_years() -> None:
    fake = FakeOpenMeteo()
    far = TODAY + timedelta(days=FORECAST_DAYS + 30)
    [weather] = asyncio.run(client_for(fake).for_dates(PARIS, [far], today=TODAY))
    assert weather.source == "typical"
    assert weather.precipitation_chance == 60  # wet in 3 of the 5 years
    assert weather.is_rainy
    assert (weather.temp_min_c, weather.temp_max_c) == (10.0, 20.0)
    assert len(fake.requests) == 5  # one archive request per past year


def test_a_trip_can_straddle_the_forecast_horizon() -> None:
    fake = FakeOpenMeteo()
    last_forecast_day = TODAY + timedelta(days=FORECAST_DAYS - 1)
    days = [last_forecast_day, last_forecast_day + timedelta(days=1)]
    result = asyncio.run(client_for(fake).for_dates(PARIS, days, today=TODAY))
    assert [w.source for w in result] == ["forecast", "typical"]
    assert [w.day for w in result] == days


def test_results_are_cached() -> None:
    fake = FakeOpenMeteo()
    client = client_for(fake)
    days = [TODAY + timedelta(days=1)]
    asyncio.run(client.for_dates(PARIS, days, today=TODAY))
    asyncio.run(client.for_dates(PARIS, days, today=TODAY))
    assert len(fake.requests) == 1


def test_upstream_errors_raise_weather_error() -> None:
    with pytest.raises(WeatherError):
        asyncio.run(client_for(FakeOpenMeteo(fail=True)).for_dates(PARIS, [TODAY], today=TODAY))

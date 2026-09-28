"""Planning with trip dates and weather through the API (rolled back after each test)."""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.api.v1.routes_route import get_weather_client
from app.main import app
from app.services.geo import LatLng
from app.services.weather import DayWeather, WeatherError
from tests.seed import CITY_ID, HOTEL

START = date.today() + timedelta(days=3)


class FakeWeather:
    def __init__(self, fail: bool = False, rainy_days: tuple[int, ...] = ()) -> None:
        self.fail = fail
        self.rainy_days = rainy_days
        self.calls: list[list[date]] = []

    async def for_dates(self, where: LatLng, days: list[date], today: date | None = None) -> list[DayWeather]:
        self.calls.append(days)
        if self.fail:
            raise WeatherError("down")
        return [
            DayWeather(
                day=d,
                source="forecast",
                condition="rain" if i in self.rainy_days else "clear",
                temp_max_c=21.0,
                temp_min_c=13.0,
                precipitation_chance=90 if i in self.rainy_days else 0,
                is_rainy=i in self.rainy_days,
            )
            for i, d in enumerate(days)
        ]


def use_weather(fake: FakeWeather | None) -> None:
    app.dependency_overrides[get_weather_client] = lambda: fake


def plan(client: TestClient, **extra) -> dict:
    body = {"city_id": CITY_ID, "accommodation": HOTEL, "duration_days": 2, **extra}
    resp = client.post("/api/v1/routes/plan", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_plan_with_dates_has_a_date_and_weather_per_day(client: TestClient) -> None:
    fake = FakeWeather(rainy_days=(1,))
    use_weather(fake)
    result = plan(client, start_date=START.isoformat())
    assert result["start_date"] == START.isoformat()
    assert [d["date"] for d in result["days"]] == [START.isoformat(), (START + timedelta(days=1)).isoformat()]
    assert [d["weather"]["is_rainy"] for d in result["days"]] == [False, True]
    assert result["days"][1]["weather"]["condition"] == "rain"
    assert fake.calls == [[START, START + timedelta(days=1)]]


def test_plan_without_dates_skips_weather(client: TestClient) -> None:
    fake = FakeWeather()
    use_weather(fake)
    result = plan(client)
    assert result["start_date"] is None
    assert all(d["date"] is None and d["weather"] is None for d in result["days"])
    assert fake.calls == []


def test_weather_outage_still_returns_a_plan(client: TestClient) -> None:
    use_weather(FakeWeather(fail=True))
    result = plan(client, start_date=START.isoformat())
    assert all(d["date"] is not None and d["weather"] is None for d in result["days"])
    assert all(d["stops"] for d in result["days"])


@pytest.mark.parametrize("offset", [-5, 400])
def test_start_date_must_be_within_a_year_from_today(client: TestClient, offset: int) -> None:
    use_weather(FakeWeather())
    body = {
        "city_id": CITY_ID,
        "accommodation": HOTEL,
        "duration_days": 1,
        "start_date": (date.today() + timedelta(days=offset)).isoformat(),
    }
    assert client.post("/api/v1/routes/plan", json=body).status_code == 422


def test_removing_a_stop_keeps_the_day_date_and_weather(client: TestClient) -> None:
    use_weather(FakeWeather(rainy_days=(0,)))
    result = plan(client, start_date=START.isoformat())
    day1 = result["days"][0]
    edited = client.post(
        "/api/v1/routes/plan/remove-stop", json={"plan": result, "poi_id": day1["stops"][0]["poi_id"]}
    ).json()
    new_day1 = edited["days"][0]
    assert new_day1["date"] == day1["date"]
    assert new_day1["weather"] == day1["weather"]
    assert new_day1["rain_adjusted"] == day1["rain_adjusted"]
    assert edited["start_date"] == result["start_date"]

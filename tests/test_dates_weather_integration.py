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


# --- reordering days -------------------------------------------------------------------------------


def reorder(client: TestClient, result: dict, order: list[int]) -> dict:
    resp = client.post("/api/v1/routes/plan/reorder-days", json={"plan": result, "day_order": order})
    assert resp.status_code == 200, resp.text
    return resp.json()


def stop_ids(day: dict) -> list[str]:
    return [s["poi_id"] for s in day["stops"]]


def test_reordering_days_without_dates_only_renumbers_them(client: TestClient) -> None:
    use_weather(FakeWeather())
    result = plan(client, duration_days=3)
    days = result["days"]
    moved = reorder(client, result, [3, 1, 2])
    assert [d["day_number"] for d in moved["days"]] == [1, 2, 3]
    assert [stop_ids(d) for d in moved["days"]] == [stop_ids(days[2]), stop_ids(days[0]), stop_ids(days[1])]
    # Same stops, same legs: only the numbers changed.
    assert {**moved["days"][0], "day_number": 3} == days[2]


def test_a_moved_day_takes_on_its_new_date_and_weather(client: TestClient) -> None:
    # Rain on day 1 sends the parks to day 2; moving day 2 to the front puts them in the rain.
    use_weather(FakeWeather(rainy_days=(0,)))
    result = plan(client, start_date=START.isoformat())
    day1, day2 = result["days"]
    assert any(s["category"] == "PARK" for s in day2["stops"])
    assert all(s["warning"] is None for d in result["days"] for s in d["stops"])

    moved = reorder(client, result, [2, 1])
    new1, new2 = moved["days"]
    assert stop_ids(new1) == stop_ids(day2) and stop_ids(new2) == stop_ids(day1)
    # Dates and weather stay with the position: day 1 is still the first, rainy date.
    assert (new1["date"], new1["weather"]) == (day1["date"], day1["weather"])
    assert (new2["date"], new2["weather"]) == (day2["date"], day2["weather"])
    assert {s["poi_id"]: s["warning"] for s in new1["stops"]} == {
        s["poi_id"]: "rain" if s["category"] == "PARK" else None for s in day2["stops"]
    }
    assert all(s["warning"] is None for s in new2["stops"])
    assert not new1["rain_adjusted"] and not new2["rain_adjusted"]
    assert moved["total_entry_cost"] == result["total_entry_cost"]


@pytest.mark.parametrize("order", [[1], [1, 1], [1, 3], [1, 2, 3]])
def test_day_order_must_list_each_day_once(client: TestClient, order: list[int]) -> None:
    use_weather(FakeWeather())
    result = plan(client)
    resp = client.post("/api/v1/routes/plan/reorder-days", json={"plan": result, "day_order": order})
    assert resp.status_code == 422

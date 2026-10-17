"""Extended report (ADR 0009): day/night HR, Heart Points, month by month, real workouts only."""

import time
from datetime import date, timedelta

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from app.config import Settings
from app.seed.loader import load_synthetic
from app.seed.synthetic import SeedConfig, generate
from tests.conftest import TODAY
from tests.helpers import post_records, record

FIRST = TODAY - timedelta(days=119)  # ~4 months: partial first month, full months, partial last


@pytest_asyncio.fixture
async def long_seed(app: FastAPI, settings: Settings) -> None:
    settings.birth_year = 1990  # fictitious: gives the synthetic data a heart-rate maximum
    cfg = SeedConfig(days=120, seed=21, end_date=TODAY, hr_interval_min=10, rest_weeks=True)
    await load_synthetic(app.state.sessionmaker, settings, generate(cfg))


def _qs(first: date, last: date) -> str:
    return f"from={first}&to={last}"


async def _report(web: httpx.AsyncClient, first: date = FIRST, last: date = TODAY) -> dict:
    r = await web.get(f"/api/v1/report?{_qs(first, last)}")
    assert r.status_code == 200, r.text
    return dict(r.json())


def _extra(body: dict) -> dict[str, dict]:
    return {m["key"]: m for m in body["extra_metrics"]}


# --------------------------------------------------------------------------- existing stays


async def check_the_twelve_existing_metrics_are_all_still_there(web: httpx.AsyncClient) -> None:
    body = await _report(web)
    assert [m["key"] for m in body["metrics"]] == [
        "steps", "heart_rate", "resting_hr", "sleep", "workouts", "active_kcal",
        "total_kcal", "distance", "weight", "spo2", "hrv", "blood_pressure",
    ]  # fmt: skip
    for key in ("current", "previous", "delta_abs", "spark", "best_day"):
        assert all(key in m for m in body["metrics"])
    assert body["sleep_regularity"] is not None and body["workouts"]["scope"] == "real"


# --------------------------------------------------------------------------- day / night heart rate


async def check_day_and_night_heart_rate_with_the_previous_period(web: httpx.AsyncClient) -> None:
    body = await _report(web)
    extra = _extra(body)
    assert {"hr_day", "hr_night", "heart_points"} <= set(extra)
    day, night = extra["hr_day"], extra["hr_night"]
    assert day["unit"] == night["unit"] == "bpm" and day["kind"] == "avg"
    assert night["current"]["avg"] < day["current"]["avg"] - 8  # asleep is lower
    # the very same definition as /heart/daypart (mean of the daily means, no real workouts)
    dp = (await web.get(f"/api/v1/heart/daypart?{_qs(FIRST, TODAY)}")).json()
    assert day["current"]["avg"] == pytest.approx(dp["summary"]["day"]["avg"])
    assert night["current"]["avg"] == pytest.approx(dp["summary"]["night"]["avg"])
    assert day["previous"]["days"] == dp["previous_summary"]["day"]["days"]
    # the first 120 days have no data before them: the previous period is empty, not an error
    assert day["previous"]["days"] == 0 and day["delta_abs"] is None


async def check_the_previous_period_of_a_later_window_has_day_and_night_values(
    web: httpx.AsyncClient,
) -> None:
    first = TODAY - timedelta(days=29)
    extra = _extra(await _report(web, first, TODAY))
    for key in ("hr_day", "hr_night"):
        assert extra[key]["previous"]["days"] > 20 and extra[key]["delta_abs"] is not None


# --------------------------------------------------------------------------- Heart Points


async def check_heart_points_total_weekly_average_and_weeks_over_the_goal(
    web: httpx.AsyncClient,
) -> None:
    body = await _report(web)
    p = body["points"]
    series = (await web.get(f"/api/v1/heart/points?{_qs(FIRST, TODAY)}&bucket=week")).json()
    assert p["total"] == pytest.approx(series["summary"]["total"]) and p["total"] > 0
    assert p["weekly_avg"] == pytest.approx(p["total"] / (body["days"] / 7))
    assert p["weeks_complete"] == series["summary"]["buckets_complete"] >= 10
    assert p["weeks_over_goal"] == series["summary"]["weeks_over_goal"]
    assert 0 < p["weeks_over_goal"] < p["weeks_complete"]  # the seed has weeks above and below
    assert p["goal"] == 150 and p["hr_configured"] is True
    extra = _extra(body)["heart_points"]
    assert extra["kind"] == "sum" and extra["current"]["total"] == pytest.approx(p["total"])


async def test_without_a_birth_year_the_report_flags_it(
    app: FastAPI, settings: Settings, web: httpx.AsyncClient
) -> None:
    cfg = SeedConfig(days=15, seed=3, end_date=TODAY, hr_interval_min=10)
    await load_synthetic(app.state.sessionmaker, settings, generate(cfg))
    assert (await _report(web, TODAY - timedelta(days=14)))["points"]["hr_configured"] is False


# --------------------------------------------------------------------------- month by month


async def check_month_by_month_table(web: httpx.AsyncClient) -> None:
    body = await _report(web)
    monthly = body["monthly"]
    cols = {c["key"]: c for c in monthly["columns"]}
    assert [c["key"] for c in monthly["columns"]][:4] == [
        "heart_rate",
        "hr_day",
        "hr_night",
        "resting_hr",
    ]
    assert {k for k, c in cols.items() if c["kind"] == "sum"} >= {
        "steps", "distance", "active_kcal", "total_kcal", "heart_points", "workouts", "workouts_s",
    }  # fmt: skip
    months = monthly["months"]
    assert len(months) in (4, 5)
    # the first and the last month are partial, the ones in between are whole
    assert months[0]["partial"] is True and months[-1]["partial"] is True
    assert all(m["partial"] is False for m in months[1:-1])
    assert months[0]["month"] == FIRST.replace(day=1).isoformat()
    assert sum(m["days"] for m in months) == body["days"]
    for m in months[1:-1]:
        d = date.fromisoformat(m["month"])
        nxt = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
        assert m["days"] == (nxt - d).days
    # totals add up to the period totals; averages are means of the daily values
    by = {m["key"]: m for m in body["metrics"]}
    steps = sum(m["values"]["steps"] or 0 for m in months)
    assert steps == pytest.approx(by["steps"]["current"]["total"])
    pts = sum(m["values"]["heart_points"] or 0 for m in months)
    assert pts == pytest.approx(body["points"]["total"])
    daily = (await web.get(f"/api/v1/report/daily?{_qs(FIRST, TODAY)}")).json()
    for m in months[1:-1]:
        rest = [
            r["values"]["resting_hr"]
            for r in daily["rows"]
            if r["date"].startswith(m["month"][:7]) and r["values"]["resting_hr"] is not None
        ]
        assert m["values"]["resting_hr"] == pytest.approx(sum(rest) / len(rest))
        night = [
            r["values"]["hr_night"]
            for r in daily["rows"]
            if r["date"].startswith(m["month"][:7]) and r["values"]["hr_night"] is not None
        ]
        assert m["values"]["hr_night"] == pytest.approx(sum(night) / len(night))
    assert months[1]["values"]["hr_day"] > months[1]["values"]["hr_night"]
    # nights with data per month: the weight of the per-night sleep mean
    assert "sleep_nights" in cols and cols["sleep_nights"]["kind"] == "sum"
    for m in months[1:-1]:
        nights = [
            r
            for r in daily["rows"]
            if r["date"].startswith(m["month"][:7]) and r["values"]["sleep_s"] is not None
        ]
        assert m["values"]["sleep_nights"] == len(nights) > 20
        assert m["values"]["sleep"] == pytest.approx(
            sum(r["values"]["sleep_s"] for r in nights) / len(nights)
        )


async def check_a_single_whole_month_has_one_row_and_is_not_partial(web: httpx.AsyncClient) -> None:
    first_of_month = (TODAY.replace(day=1) - timedelta(days=1)).replace(day=1)  # last month
    last_of_month = TODAY.replace(day=1) - timedelta(days=1)
    body = await _report(web, first_of_month, last_of_month)
    months = body["monthly"]["months"]
    assert len(months) == 1 and months[0]["partial"] is False
    assert months[0]["days"] == (last_of_month - first_of_month).days + 1


async def check_a_week_across_two_months_has_two_partial_rows(web: httpx.AsyncClient) -> None:
    last_of_month = TODAY.replace(day=1) - timedelta(days=1)
    first, last = last_of_month - timedelta(days=2), last_of_month + timedelta(days=3)
    months = (await _report(web, first, last))["monthly"]["months"]
    assert [m["days"] for m in months] == [3, 3] and all(m["partial"] for m in months)


# --------------------------------------------------------------------------- real workouts only


async def check_workouts_are_real_only_per_month_and_per_type(web: httpx.AsyncClient) -> None:
    body = await _report(web)
    w = body["workouts"]
    sessions = (await web.get(f"/api/v1/exercise/sessions?{_qs(FIRST, TODAY)}&scope=real")).json()
    assert w["scope"] == "real" and w["count"] == sessions["summary"]["count"] > 5
    assert w["excluded"] > 0  # the walks and the short ride are left out
    detail = {d["type"]: d for d in w["by_type_detail"]}
    assert "WALKING" not in detail and {"RUNNING", "BIKING"} <= set(detail)
    assert sum(d["count"] for d in detail.values()) == w["count"]
    assert sum(d["duration_s"] for d in detail.values()) == pytest.approx(w["duration_s"])
    assert [d["duration_s"] for d in w["by_type_detail"]] == sorted(
        (d["duration_s"] for d in w["by_type_detail"]), reverse=True
    )
    months = body["monthly"]["months"]
    assert sum(m["values"]["workouts"] or 0 for m in months) == w["count"]
    assert sum(m["values"]["workouts_s"] or 0 for m in months) == pytest.approx(w["duration_s"])


async def check_a_manual_verdict_moves_a_session_in_and_out_of_the_report(
    web: httpx.AsyncClient,
) -> None:
    before = (await _report(web))["workouts"]["count"]
    rows = (await web.get(f"/api/v1/exercise/sessions?{_qs(FIRST, TODAY)}&scope=all")).json()[
        "sessions"
    ]
    walk = next(s for s in rows if s["type"] == "WALKING" and not s["is_real"])
    r = await web.put(
        f"/api/v1/exercise/sessions/{walk['id']}/override",
        json={"value": True},
        headers={"X-SBH-Client": "web"},
    )
    assert r.status_code == 200
    after = await _report(web)
    assert after["workouts"]["count"] == before + 1
    assert any(d["type"] == "WALKING" for d in after["workouts"]["by_type_detail"])
    assert sum(m["values"]["workouts"] or 0 for m in after["monthly"]["months"]) == before + 1


# --------------------------------------------------------------------------- CSV and performance


async def check_the_daily_csv_has_the_day_night_and_points_columns(web: httpx.AsyncClient) -> None:
    daily = (await web.get(f"/api/v1/report/daily?{_qs(TODAY - timedelta(days=20), TODAY)}")).json()
    keys = [c["key"] for c in daily["columns"]]
    assert {"hr_day", "hr_night", "heart_points"} <= set(keys)
    assert keys.index("hr_day") == keys.index("hr_max") + 1
    labels = {c["key"]: c["label"] for c in daily["columns"]}
    assert (labels["hr_day"], labels["hr_night"], labels["heart_points"]) == (
        "FC diurna",
        "FC notturna",
        "Punti cardio",
    )
    full = [r for r in daily["rows"] if r["values"]["hr_day"] and r["values"]["hr_night"]]
    assert len(full) > 10 and all(r["values"]["hr_night"] < r["values"]["hr_day"] for r in full)
    assert any((r["values"]["heart_points"] or 0) > 0 for r in daily["rows"])
    # a few days are not enough for day AND night on the very first day: no error either way
    assert all("heart_points" in r["values"] for r in daily["rows"])


async def test_a_ten_year_period_stays_usable(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    await post_records(
        client,
        auth,
        [
            record(
                "Weight",
                "w1",
                f"{TODAY - timedelta(days=3000)}T07:00:00+02:00",
                None,
                {"value": 80.0},
            )
        ],
    )
    first = TODAY - timedelta(days=3659)
    started = time.monotonic()
    body = await _report(web, first, TODAY)
    assert time.monotonic() - started < 30
    assert len(body["monthly"]["months"]) in (120, 121, 122)
    weight = [
        m["values"]["weight"]
        for m in body["monthly"]["months"]
        if m["values"]["weight"] is not None
    ]
    assert weight == [80.0]
    too_long = await web.get(f"/api/v1/report?{_qs(TODAY - timedelta(days=4000), TODAY)}")
    assert too_long.status_code == 422


async def test_empty_period(web: httpx.AsyncClient) -> None:
    body = await _report(web, TODAY - timedelta(days=6), TODAY)
    assert body["points"]["total"] == 0 and body["points"]["weeks_over_goal"] == 0
    assert all(m["days_with_data"] == 0 for m in body["extra_metrics"])
    assert all(v is None or v == 0 for m in body["monthly"]["months"] for v in m["values"].values())


async def test_the_extended_report_on_four_months_of_data(
    long_seed: None, web: httpx.AsyncClient
) -> None:
    """One seeding (about half a minute), all the checks: each is a separate scenario."""
    await check_the_twelve_existing_metrics_are_all_still_there(web)
    await check_day_and_night_heart_rate_with_the_previous_period(web)
    await check_the_previous_period_of_a_later_window_has_day_and_night_values(web)
    await check_heart_points_total_weekly_average_and_weeks_over_the_goal(web)
    await check_month_by_month_table(web)
    await check_a_single_whole_month_has_one_row_and_is_not_partial(web)
    await check_a_week_across_two_months_has_two_partial_rows(web)
    await check_workouts_are_real_only_per_month_and_per_type(web)
    await check_the_daily_csv_has_the_day_night_and_points_columns(web)
    await check_a_manual_verdict_moves_a_session_in_and_out_of_the_report(web)

"""Trends: moving average, previous period, bands, coarsening, sleep nights, workouts, report."""

from datetime import date, timedelta

import httpx
import pytest

from app.dash_schemas import SeriesPoint
from app.services.analytics import previous_range
from app.services.queries import _bucket_count, _moving_average, bucket_start
from tests.conftest import TODAY
from tests.helpers import post_records, record, steps


def _qs(first: date, last: date, **extra: object) -> str:
    parts = [f"from={first}", f"to={last}", *[f"{k}={v}" for k, v in extra.items()]]
    return "&".join(parts)


# --------------------------------------------------------------------------- pure helpers


def test_moving_average_is_trailing_and_ignores_gaps() -> None:
    pts = [SeriesPoint(t=str(i), v=v) for i, v in enumerate([1, 2, None, 4, 5, 6, 7, 8])]
    _moving_average(pts, 3)
    assert [p.ma for p in pts] == [1, 1.5, 1.5, 3, 4.5, 5, 6, 7]


def test_previous_range_is_adjacent_and_same_length() -> None:
    assert previous_range(date(2026, 10, 9), date(2026, 10, 15)) == (
        date(2026, 10, 2),
        date(2026, 10, 8),
    )
    assert previous_range(date(2026, 10, 15), date(2026, 10, 15)) == (
        date(2026, 10, 14),
        date(2026, 10, 14),
    )


def test_buckets_start_on_monday_and_first_of_month() -> None:
    assert bucket_start(date(2026, 10, 25), "week") == date(2026, 10, 19)  # a Sunday -> Monday
    assert bucket_start(date(2026, 10, 19), "week") == date(2026, 10, 19)
    assert bucket_start(date(2026, 10, 31), "month") == date(2026, 10, 1)
    assert _bucket_count(3000, "day") == 3000 and _bucket_count(3000, "week") == 429


# --------------------------------------------------------------------------- series options


async def test_series_moving_average_compare_and_band(seeded: None, web: httpx.AsyncClient) -> None:
    first = TODAY - timedelta(days=4)
    r = await web.get(
        "/api/v1/metrics/HeartRate/series?"
        + _qs(first, TODAY, bucket="day", band="true", ma="true", compare="true")
    )
    body = r.json()
    assert r.status_code == 200 and body["bucket"] == "day" and body["ma_window"] == 7
    pts = body["points"]
    assert len(pts) == 5
    for p in pts:
        assert p["lo"] <= p["v"] <= p["hi"]
        assert p["ma"] is not None
    # trailing window: the first point's average is itself
    assert pts[0]["ma"] == pytest.approx(pts[0]["v"])
    # previous period = the 5 days before: seed covers 10 days, so all of them have data
    assert body["previous_from"] == str(first - timedelta(days=5))
    assert body["previous_to"] == str(first - timedelta(days=1))
    assert all(p["prev"] is not None for p in pts)
    assert body["previous_summary"]["points"] == 5


async def test_series_without_options_has_no_extras(seeded: None, web: httpx.AsyncClient) -> None:
    first = TODAY - timedelta(days=4)
    body = (
        await web.get(f"/api/v1/metrics/HeartRate/series?{_qs(first, TODAY, bucket='day')}")
    ).json()
    assert all(p["lo"] is None and p["ma"] is None and p["prev"] is None for p in body["points"])
    assert body["previous_summary"] is None and body["ma_window"] is None


async def test_compare_for_the_first_period_has_empty_previous(
    seeded: None, web: httpx.AsyncClient
) -> None:
    first = TODAY - timedelta(days=9)
    body = (
        await web.get(
            f"/api/v1/metrics/Steps/series?{_qs(first, TODAY, bucket='day', compare='true')}"
        )
    ).json()
    assert body["previous_summary"]["points"] == 0
    assert all(p["prev"] is None for p in body["points"])


async def test_series_coarsens_long_ranges(web: httpx.AsyncClient) -> None:
    first = TODAY - timedelta(days=3000)
    r = await web.get(f"/api/v1/metrics/Steps/series?{_qs(first, TODAY, bucket='day')}")
    body = r.json()
    assert r.status_code == 200
    assert body["coarsened"] is True and body["bucket"] == "week"
    assert len(body["points"]) <= 1000
    assert body["points"][0]["t"] <= str(first + timedelta(days=6))
    # short ranges are left alone
    short = (
        await web.get(
            f"/api/v1/metrics/Steps/series?{_qs(TODAY - timedelta(days=30), TODAY, bucket='day')}"
        )
    ).json()
    assert short["coarsened"] is False and short["bucket"] == "day"


async def test_week_buckets_use_italian_weeks_and_rome_days(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    # 22:30Z on Sat 24/10 is 00:30 on Sun 25/10 in Rome (CEST): Sunday, week of 19/10
    # 23:30Z on Sun 25/10 is 00:30 on Mon 26/10 in Rome (CET after the DST change): next week.
    await post_records(
        client,
        auth,
        [
            steps("a", "2026-10-24T22:30:00Z", "2026-10-24T22:45:00Z", 100, offset=None),
            steps("b", "2026-10-25T23:30:00Z", "2026-10-25T23:45:00Z", 40, offset=None),
        ],
    )
    day = (
        await web.get(
            "/api/v1/metrics/Steps/series?from=2026-10-24&to=2026-10-26&bucket=day&source=computed"
        )
    ).json()
    assert {p["t"]: p["v"] for p in day["points"]} == {
        "2026-10-24": None,
        "2026-10-25": 100,
        "2026-10-26": 40,
    }
    week = (
        await web.get(
            "/api/v1/metrics/Steps/series?from=2026-10-19&to=2026-10-26&bucket=week&source=computed"
        )
    ).json()
    assert {p["t"]: p["v"] for p in week["points"]} == {"2026-10-19": 100, "2026-10-26": 40}


async def test_blood_pressure_series_uses_field_and_handles_no_data(
    web: httpx.AsyncClient, seeded: None
) -> None:
    first = TODAY - timedelta(days=9)
    sys_ = (
        await web.get(f"/api/v1/metrics/BloodPressure/series?{_qs(first, TODAY, bucket='day')}")
    ).json()
    dia = (
        await web.get(
            "/api/v1/metrics/BloodPressure/series?"
            + _qs(first, TODAY, bucket="day", field="diastolic")
        )
    ).json()
    s_vals = [p["v"] for p in sys_["points"] if p["v"] is not None]
    d_vals = [p["v"] for p in dia["points"] if p["v"] is not None]
    assert len(s_vals) == len(d_vals) >= 3
    assert min(s_vals) > max(d_vals) and dia["field"] == "diastolic"
    bad = await web.get("/api/v1/metrics/Steps/series?field=diastolic")
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_field"


async def test_blood_pressure_without_data_is_empty_not_an_error(web: httpx.AsyncClient) -> None:
    body = (
        await web.get(
            f"/api/v1/metrics/BloodPressure/series?{_qs(TODAY - timedelta(days=30), TODAY)}"
        )
    ).json()
    assert body["summary"]["points"] == 0 and all(p["v"] is None for p in body["points"])


# --------------------------------------------------------------------------- bounds


async def test_bounds(web: httpx.AsyncClient, seeded: None) -> None:
    body = (await web.get("/api/v1/data/bounds")).json()
    assert body["last"] == str(TODAY) and body["first"] == str(TODAY - timedelta(days=9))


async def test_bounds_on_empty_database(web: httpx.AsyncClient) -> None:
    assert (await web.get("/api/v1/data/bounds")).json() == {"first": None, "last": None}


# --------------------------------------------------------------------------- sleep


async def test_sleep_nights_clock_minutes_use_rome_time(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    # 23:00 CEST -> 06:30 CEST: bedtime is 300 min after 18:00, wake is 390 min after midnight
    await post_records(
        client,
        auth,
        [
            record(
                "SleepSession", "n1", "2026-10-13T23:00:00+02:00", "2026-10-14T06:30:00+02:00", {}
            )
        ],
    )
    # across the DST change (night of 24->25 Oct has 25 hours): 23:30 CEST -> 07:00 CET
    await post_records(
        client,
        auth,
        [
            record(
                "SleepSession", "n2", "2026-10-24T23:30:00+02:00", "2026-10-25T07:00:00+01:00", {}
            )
        ],
    )
    body = (await web.get("/api/v1/sleep/nights?from=2026-10-01&to=2026-10-31")).json()
    by_date = {n["date"]: n for n in body["nights"]}
    assert by_date["2026-10-14"]["bedtime_min"] == 300 and by_date["2026-10-14"]["wake_min"] == 390
    assert by_date["2026-10-14"]["asleep_s"] == 7.5 * 3600
    assert by_date["2026-10-25"]["bedtime_min"] == 330 and by_date["2026-10-25"]["wake_min"] == 420
    assert body["summary"]["nights"] == 2
    assert body["summary"]["bedtime_sd_min"] == pytest.approx(15.0)  # 300 vs 330 -> pstdev 15


async def test_sleep_nights_seeded_has_stages_and_previous(
    seeded: None, web: httpx.AsyncClient
) -> None:
    first = TODAY - timedelta(days=4)
    body = (await web.get(f"/api/v1/sleep/nights?{_qs(first, TODAY)}")).json()
    assert len(body["nights"]) == 5 and body["summary"]["nights"] == 5
    night = body["nights"][-1]
    assert {"light", "deep"} <= set(night["stages_s"]) and night["in_bed_s"] >= night["asleep_s"]
    assert 240 <= night["bedtime_min"] <= 420 and 300 <= night["wake_min"] <= 480
    assert body["previous"]["nights"] == 5
    assert (await web.get(f"/api/v1/sleep/nights?from={TODAY}&to={first}")).status_code == 422


# --------------------------------------------------------------------------- workouts


async def test_exercise_sessions_dedupe_kcal_hr_and_weekly(
    seeded: None, web: httpx.AsyncClient
) -> None:
    first = TODAY - timedelta(days=9)
    body = (await web.get(f"/api/v1/exercise/sessions?{_qs(first, TODAY)}")).json()
    sessions = body["sessions"]
    assert 4 <= len(sessions) <= 6  # every other day; the phone's copy of each is not listed
    assert len({s["start"] for s in sessions}) == len(sessions)
    assert {"WALKING", "RUNNING", "BIKING"} <= {s["type"] for s in sessions}
    assert all(s["kcal"] and s["kcal"] > 0 for s in sessions)
    assert all(s["avg_hr"] and 40 < s["avg_hr"] < 190 for s in sessions)
    assert [s["start"] for s in sessions] == sorted((s["start"] for s in sessions), reverse=True)
    summary = body["summary"]
    assert summary["count"] == len(sessions) == sum(w["count"] for w in body["weekly"])
    assert summary["duration_s"] == pytest.approx(sum(s["duration_s"] for s in sessions))
    assert sum(summary["by_type"].values()) == summary["count"]
    assert body["weekly"][0]["week_start"] <= str(first) and len(body["weekly"]) in (2, 3)
    assert body["previous"]["count"] >= 0


async def test_exercise_with_no_data(web: httpx.AsyncClient) -> None:
    body = (await web.get("/api/v1/exercise/sessions")).json()
    assert (
        body["sessions"] == [] and body["summary"]["count"] == 0 and body["summary"]["kcal"] is None
    )


# --------------------------------------------------------------------------- report


async def test_report_covers_the_twelve_metrics(seeded: None, web: httpx.AsyncClient) -> None:
    first = TODAY - timedelta(days=4)
    r = await web.get(f"/api/v1/report?{_qs(first, TODAY)}")
    body = r.json()
    assert r.status_code == 200 and body["days"] == 5
    assert [m["key"] for m in body["metrics"]] == [
        "steps",
        "heart_rate",
        "resting_hr",
        "sleep",
        "workouts",
        "active_kcal",
        "total_kcal",
        "distance",
        "weight",
        "spo2",
        "hrv",
        "blood_pressure",
    ]
    by = {m["key"]: m for m in body["metrics"]}
    steps_ = by["steps"]
    assert steps_["kind"] == "sum" and steps_["days_with_data"] == 5
    assert steps_["current"]["total"] == pytest.approx(
        sum(v for v in steps_["spark"] if v is not None)
    )
    assert steps_["delta_abs"] == pytest.approx(
        steps_["current"]["total"] - steps_["previous"]["total"]
    )
    assert steps_["best_day"]["value"] == steps_["current"]["max"]
    assert steps_["worst_day"]["value"] == steps_["current"]["min"]
    assert steps_["unit"] == "count"
    # lower resting heart rate is the better day
    rhr = by["resting_hr"]
    assert rhr["best_day"]["value"] == rhr["current"]["min"] and rhr["higher_is_better"] is False
    # heart rate: no judgement, but the real extremes of the period
    hr = by["heart_rate"]
    assert (
        hr["best_day"] is None
        and hr["current"]["min"] < hr["current"]["avg"] < hr["current"]["max"]
    )
    assert by["weight"]["best_day"] is None and by["weight"]["first"] is not None
    assert by["sleep"]["unit"] == "s" and by["sleep"]["current"]["avg"] > 3 * 3600
    assert (
        body["sleep_regularity"]["nights"] == 5 and body["sleep_regularity"]["bedtime_sd_min"] >= 0
    )
    assert body["workouts"]["count"] >= 1 and body["workouts"]["per_week"] > 0
    assert by["workouts"]["sessions"] >= 1
    assert body["previous_to"] == str(first - timedelta(days=1))


async def test_report_blood_pressure_has_both_values(seeded: None, web: httpx.AsyncClient) -> None:
    body = (await web.get(f"/api/v1/report?{_qs(TODAY - timedelta(days=9), TODAY)}")).json()
    bp = next(m for m in body["metrics"] if m["key"] == "blood_pressure")
    assert bp["days_with_data"] >= 3 and bp["diastolic"]["avg"] < bp["current"]["avg"]


async def test_report_long_period_shrinks_sparklines(web: httpx.AsyncClient) -> None:
    body = (await web.get(f"/api/v1/report?{_qs(TODAY - timedelta(days=364), TODAY)}")).json()
    assert body["metrics"][0]["spark_bucket"] == "week" and len(body["metrics"][0]["spark"]) <= 54


async def test_report_without_data_is_all_empty(web: httpx.AsyncClient) -> None:
    body = (await web.get(f"/api/v1/report?{_qs(TODAY - timedelta(days=6), TODAY)}")).json()
    assert all(m["days_with_data"] == 0 and m["best_day"] is None for m in body["metrics"])
    assert body["sleep_regularity"] is None and body["workouts"]["count"] == 0


async def test_report_daily_table(seeded: None, web: httpx.AsyncClient) -> None:
    first = TODAY - timedelta(days=4)
    body = (await web.get(f"/api/v1/report/daily?{_qs(first, TODAY)}")).json()
    assert len(body["columns"]) == 16 and len(body["rows"]) == 5
    assert [r["date"] for r in body["rows"]] == sorted(r["date"] for r in body["rows"])
    last = body["rows"][-1]["values"]
    steps_series = (
        await web.get(f"/api/v1/metrics/Steps/series?{_qs(TODAY, TODAY, bucket='day')}")
    ).json()
    assert last["steps"] == steps_series["points"][0]["v"]  # same official value as the charts
    assert last["hr_min"] < last["hr_avg"] < last["hr_max"] and last["sleep_s"] > 3 * 3600
    assert set(last) == {c["key"] for c in body["columns"]}
    too_long = await web.get(f"/api/v1/report/daily?{_qs(TODAY - timedelta(days=4000), TODAY)}")
    assert too_long.status_code == 422 and too_long.json()["error"]["code"] == "range_too_long"

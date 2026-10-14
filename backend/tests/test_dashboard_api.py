"""Dashboard read API over synthetic data."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from app.config import Settings
from app.seed.loader import load_synthetic
from app.seed.synthetic import PHONE, SCALE, WATCH, SeedConfig, generate
from tests.helpers import post_records, steps

TODAY = datetime.now(ZoneInfo("Europe/Rome")).date()


@pytest_asyncio.fixture
async def seeded(app: FastAPI, settings: Settings) -> None:
    data = generate(SeedConfig(days=10, seed=3, end_date=TODAY, hr_interval_min=10))
    await load_synthetic(app.state.sessionmaker, settings, data)


@pytest_asyncio.fixture
async def web(client: httpx.AsyncClient, admin_password: str) -> httpx.AsyncClient:
    r = await client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": admin_password},
        headers={"X-SBH-Client": "web"},
    )
    assert r.status_code == 200
    return client


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/summary/today",
        "/api/v1/metrics/Steps/series",
        "/api/v1/data/inventory",
        "/api/v1/data/reconciliation",
        "/api/v1/sync/status",
    ],
)
async def test_read_api_requires_a_session(
    client: httpx.AsyncClient, auth: dict[str, str], path: str
) -> None:
    assert (await client.get(path)).status_code == 401
    assert (await client.get(path, headers=auth)).status_code == 401  # ingest token is not enough


async def test_summary_today(seeded: None, web: httpx.AsyncClient) -> None:
    r = await web.get("/api/v1/summary/today")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["date"] == TODAY.isoformat() and body["timezone"] == "Europe/Rome"
    steps_ = body["steps"]
    assert steps_["source"] == "hc_official" and steps_["value"] == steps_["official"] > 0
    assert steps_["computed"] is not None
    assert body["heart"]["current"]["value"] > 30
    assert body["heart"]["resting"]["value"] is not None
    assert body["spo2"]["value"] is not None and body["hrv"]["value"] is not None
    sleep = body["sleep"]
    assert sleep["asleep_s"] > 3 * 3600 and sleep["sessions"] == 1
    assert {"light", "deep"} <= set(sleep["stages_s"])
    acts = body["activities"]
    assert 1 <= len(acts) <= 5
    starts = [a["start"] for a in acts]
    assert len(set(starts)) == len(starts)  # the phone/watch duplicate walk appears once
    assert body["last_sync_at"] is not None


async def test_summary_on_empty_database_is_all_nulls(web: httpx.AsyncClient) -> None:
    body = (await web.get("/api/v1/summary/today")).json()
    assert body["steps"]["value"] is None and body["sleep"] is None
    assert body["heart"]["current"] is None and body["activities"] == []


async def test_series_day_week_month(seeded: None, web: httpx.AsyncClient) -> None:
    first = (TODAY - timedelta(days=6)).isoformat()
    r = await web.get(f"/api/v1/metrics/Steps/series?from={first}&to={TODAY}&bucket=day")
    body = r.json()
    assert r.status_code == 200 and body["bucket"] == "day" and body["agg"] == "sum"
    assert body["from"] == first and len(body["points"]) == 7
    assert body["source_counts"] == {"hc_official": 7}
    assert body["summary"]["points"] == 7
    assert body["summary"]["total"] == pytest.approx(sum(p["v"] for p in body["points"]))

    week = (
        await web.get(
            f"/api/v1/metrics/Steps/series?from={first}&to={TODAY}&bucket=week&source=computed"
        )
    ).json()
    assert 1 <= len(week["points"]) <= 2 and week["source_counts"] == {"computed": 7}
    assert sum(p["v"] or 0 for p in week["points"]) > 0

    month = (
        await web.get(f"/api/v1/metrics/Steps/series?from={first}&to={TODAY}&bucket=month")
    ).json()
    assert 1 <= len(month["points"]) <= 2 and month["points"][0]["t"].endswith("-01")


async def test_series_intraday_heart_rate(seeded: None, web: httpx.AsyncClient) -> None:
    r = await web.get(f"/api/v1/metrics/HeartRate/series?from={TODAY}&to={TODAY}")
    body = r.json()
    assert body["bucket"] == "15min" and body["agg"] == "avg" and body["unit"] == "bpm"
    assert 20 <= len(body["points"]) <= 96
    assert all(35 <= p["v"] <= 200 for p in body["points"])
    assert body["points"][0]["t"].startswith(TODAY.isoformat()) and "+0" in body["points"][0]["t"]

    hourly = (
        await web.get(
            f"/api/v1/metrics/HeartRate/series?from={TODAY}&to={TODAY}&bucket=hour&agg=max"
        )
    ).json()
    assert hourly["bucket"] == "hour" and len(hourly["points"]) <= 24

    steps_h = (
        await web.get(f"/api/v1/metrics/Steps/series?from={TODAY}&to={TODAY}&bucket=hour")
    ).json()
    day_total = (
        await web.get(
            f"/api/v1/metrics/Steps/series?from={TODAY}&to={TODAY}&bucket=day&source=computed"
        )
    ).json()["points"][0]["v"]
    # hourly values come from the same de-duplicated records as the daily total
    assert sum(p["v"] for p in steps_h["points"]) == pytest.approx(day_total)


async def test_series_validation(seeded: None, web: httpx.AsyncClient) -> None:
    first = (TODAY - timedelta(days=30)).isoformat()
    r = await web.get(f"/api/v1/metrics/Steps/series?from={first}&to={TODAY}&bucket=hour")
    assert r.status_code == 422 and r.json()["error"]["code"] == "bucket_too_fine"
    r = await web.get("/api/v1/metrics/Nope/series")
    assert r.status_code == 404
    r = await web.get("/api/v1/metrics/HeartRate/series?agg=sum")
    assert r.status_code == 422 and r.json()["error"]["code"] == "agg_not_supported"
    r = await web.get("/api/v1/metrics/SleepSession/series?bucket=hour")
    assert r.status_code == 422 and r.json()["error"]["code"] == "bucket_not_supported"
    r = await web.get(f"/api/v1/metrics/Steps/series?from={TODAY}&to={first}")
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_range"
    r = await web.get("/api/v1/metrics/Steps/series?bucket=decade")
    assert r.status_code == 422


async def test_series_auto_bucket_by_range(seeded: None, web: httpx.AsyncClient) -> None:
    async def bucket(days: int, type_: str = "Steps") -> str:
        first = (TODAY - timedelta(days=days - 1)).isoformat()
        r = await web.get(f"/api/v1/metrics/{type_}/series?from={first}&to={TODAY}")
        return str(r.json()["bucket"])

    assert await bucket(1) == "15min"
    assert await bucket(7) == "hour"
    assert await bucket(30) == "day"
    assert await bucket(200) == "week"
    assert await bucket(1000) == "month"
    assert await bucket(1, "SleepSession") == "day"


async def test_inventory_counts_per_type_and_source(
    seeded: None, web: httpx.AsyncClient, app: FastAPI
) -> None:
    body = (await web.get("/api/v1/data/inventory")).json()
    types = {t["type"]: t for t in body["types"]}
    assert {PHONE, WATCH} == {s["package"] for s in types["Steps"]["sources"]}
    assert {SCALE, PHONE} == {s["package"] for s in types["Weight"]["sources"]}
    assert types["HeartRate"]["samples"] > 1000 and types["Steps"]["samples"] == 0
    assert types["Steps"]["official_days"] == 10 and types["Steps"]["computed_days"] == 10
    assert types["Steps"]["first"] < types["Steps"]["last"]
    assert body["records"] == sum(t["records"] for t in body["types"])
    assert {s["package"] for s in body["sources"]} == {PHONE, WATCH, SCALE}
    watch = next(s for s in body["sources"] if s["package"] == WATCH)
    assert "HeartRate" in watch["types"]


async def test_reconciliation_flags_double_counting(seeded: None, web: httpx.AsyncClient) -> None:
    body = (await web.get("/api/v1/data/reconciliation?types=Steps")).json()
    rows = body["rows"]
    assert len(rows) == 14 or len(rows) >= 9  # seeded 10 days inside the default 14-day window
    row = rows[0]
    assert row["date"] == TODAY.isoformat() and row["type"] == "Steps"
    assert row["status"] == "match" and row["diff"] == pytest.approx(0, abs=1)
    # both phone and watch wrote the same quarter-hours: a blind sum overshoots badly
    assert row["naive"] > row["official"] * 1.5 and row["naive_exceeds_official"] is True
    by_pkg = {s["package"]: s for s in row["sources"]}
    assert set(by_pkg) == {PHONE, WATCH}
    assert by_pkg[PHONE]["counted"] == pytest.approx(row["official"])
    assert by_pkg[WATCH]["counted"] == pytest.approx(0, abs=1)
    assert body["summary"]["overlap_rows"] == body["summary"]["rows"] > 0

    sleep = (await web.get("/api/v1/data/reconciliation?types=SleepSession")).json()["rows"]
    assert sleep and sleep[0]["naive"] > sleep[0]["computed"]  # phone's duplicate night excluded

    bad = await web.get("/api/v1/data/reconciliation?types=HeartRate")
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "type_not_supported"
    far = (TODAY - timedelta(days=400)).isoformat()
    assert (await web.get(f"/api/v1/data/reconciliation?from={far}")).status_code == 422


async def test_reconciliation_without_official_is_reported(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    day = TODAY.isoformat()
    await post_records(
        client,
        auth,
        [steps("a", f"{day}T08:00:00+02:00", f"{day}T08:15:00+02:00", 100, pkg="p1")],
    )
    row = (await web.get("/api/v1/data/reconciliation?types=Steps")).json()["rows"][0]
    assert row["status"] == "no_official" and row["official"] is None and row["computed"] == 100


async def test_sync_status_lists_rejections_and_errors(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    from tests.helpers import DEVICE, SYNC, post, record

    day = TODAY.isoformat()
    ok = steps("ok", f"{day}T08:00:00+02:00", f"{day}T08:15:00+02:00", 5)
    bad = steps("bad", f"{day}T08:00:00+02:00", f"{day}T08:15:00+02:00", -1)
    await post_records(
        client,
        auth,
        [ok, bad, bad | {"hc_id": "bad2"}, record("Nope", "n", f"{day}T08:00:00+02:00", None, {})],
    )
    await post(
        client,
        auth,
        "sync-report",
        {
            "device_id": DEVICE,
            "sync_id": SYNC,
            "device": {"name": "Test phone", "app_version": "9.9"},
            "mode": "incremental",
            "status": "partial",
            "started_at": f"{day}T08:00:00Z",
            "finished_at": f"{day}T08:00:05Z",
            "counts": {"records_sent": 4},
            "errors": [{"code": "type_read_failed", "type": "Power", "count": 1}],
        },
    )
    body = (await web.get("/api/v1/sync/status")).json()
    assert body["last_success_at"] is not None
    assert body["devices"][0]["name"] == "Test phone" and body["devices"][0]["app_version"] == "9.9"
    run = body["runs"][0]
    assert run["device_name"] == "Test phone" and run["status"] == "partial"
    assert (run["received"], run["inserted"], run["rejected"]) == (4, 1, 3)
    tally = {(t["type"], t["reason"]): t["count"] for t in run["rejections"]}
    assert tally == {("Steps", "invalid_record"): 2, ("Nope", "unsupported_type"): 1}
    assert run["errors"][0]["code"] == "type_read_failed"
    assert run["duration_s"] == 5
    assert "-1" not in str(run["rejections"])  # no values in the tally

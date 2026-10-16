"""Heart rate by day part: night = inside sleep sessions, fallback 23:00-07:00, day = the rest."""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI

from app.config import Settings
from app.seed.loader import load_synthetic
from app.seed.synthetic import SeedConfig, generate
from app.services.daypart import DayStats, Span, bucket_points, fixed_night, merge_spans
from tests.conftest import TODAY
from tests.helpers import DEVICE, post_records, record

ROME = ZoneInfo("Europe/Rome")


def _utc(*a: int) -> datetime:
    return datetime(*a, tzinfo=UTC)


# --------------------------------------------------------------------------- pure helpers


def test_fixed_night_is_23_to_07_local_and_dst_aware() -> None:
    # summer time: 23:00 CEST = 21:00Z; the night of 25 Oct 2026 crosses the switch to CET
    assert fixed_night(date(2026, 10, 20), ROME) == (_utc(2026, 10, 19, 21), _utc(2026, 10, 20, 5))
    start, end = fixed_night(date(2026, 10, 25), ROME)
    assert start == _utc(2026, 10, 24, 21) and end == _utc(2026, 10, 25, 6)  # 9 h, not 8


def test_merge_spans_unites_overlaps_and_keeps_the_wake_day() -> None:
    a = Span(_utc(2026, 10, 1, 21), _utc(2026, 10, 2, 5), date(2026, 10, 2), "sleep")
    b = Span(_utc(2026, 10, 1, 21, 5), _utc(2026, 10, 2, 5, 30), date(2026, 10, 2), "sleep")
    c = Span(_utc(2026, 10, 2, 21), _utc(2026, 10, 3, 5), date(2026, 10, 3), "fixed")
    merged = merge_spans([c, b, a])
    assert [(m.start, m.end, m.day, m.source) for m in merged] == [
        (a.start, b.end, date(2026, 10, 2), "sleep"),
        (c.start, c.end, date(2026, 10, 3), "fixed"),
    ]


def test_buckets_weight_by_samples() -> None:
    days = {
        date(2026, 10, 12): DayStats(day_avg=70, day_n=10, night_avg=50, night_n=2),
        date(2026, 10, 13): DayStats(day_avg=80, day_n=30, night_avg=None, night_n=0),
        date(2026, 10, 19): DayStats(day_avg=60, day_n=5),
    }
    week = bucket_points(days, "week")
    assert [p.t for p in week] == ["2026-10-12", "2026-10-19"]
    assert week[0].day == 77.5 and week[0].night == 50 and week[0].day_n == 40
    assert week[1].night is None
    assert len(bucket_points(days, "month")) == 1


# --------------------------------------------------------------------------- API


def _hr(hc: str, start: str, end: str, samples: list[tuple[str, int]]) -> dict[str, object]:
    return record(
        "HeartRate",
        hc,
        start,
        end,
        {"samples": [{"time": t, "value": v} for t, v in samples]},
    )


async def _post_two_days(client: httpx.AsyncClient, auth: dict[str, str]) -> None:
    sleep: dict[str, object] = {"title": "Night", "stages": []}
    await post_records(
        client,
        auth,
        [
            # 14 Oct: recorded (two apps, overlapping); 15 Oct: no session -> fixed window
            record(
                "SleepSession",
                "s1",
                "2026-10-13T23:30:00+02:00",
                "2026-10-14T06:30:00+02:00",
                sleep,
            ),
            record(
                "SleepSession",
                "s2",
                "2026-10-13T23:35:00+02:00",
                "2026-10-14T06:25:00+02:00",
                sleep,
                pkg="pkg.b",
            ),
            _hr(
                "h1",
                "2026-10-13T22:00:00+02:00",
                "2026-10-14T08:00:00+02:00",
                [
                    ("2026-10-13T22:00:00+02:00", 80),  # 13 Oct, outside the asked range
                    ("2026-10-13T23:45:00+02:00", 48),  # night of the 14th
                    ("2026-10-14T00:00:00+02:00", 50),
                    ("2026-10-14T03:00:00+02:00", 52),
                    ("2026-10-14T06:00:00+02:00", 54),
                    ("2026-10-14T06:45:00+02:00", 70),  # awake
                ],
            ),
            _hr(
                "h2",
                "2026-10-14T22:00:00+02:00",
                "2026-10-15T13:00:00+02:00",
                [
                    ("2026-10-14T22:59:00+02:00", 90),  # still day
                    ("2026-10-14T23:00:00+02:00", 60),  # fixed night of the 15th starts
                    ("2026-10-15T02:00:00+02:00", 58),
                    ("2026-10-15T06:59:00+02:00", 56),
                    ("2026-10-15T07:00:00+02:00", 75),  # day again
                    ("2026-10-15T12:00:00+02:00", 85),
                ],
            ),
        ],
    )


async def test_daypart_needs_a_session(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/heart/daypart")).status_code == 401


async def test_daypart_sleep_sessions_fallback_and_summary(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    await _post_two_days(client, auth)
    r = await web.get("/api/v1/heart/daypart?from=2026-10-14&to=2026-10-15")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["bucket"] == "day" and body["fixed_window"] == "23:00-07:00"
    p14, p15 = body["points"]
    assert (p14["t"], p14["night"], p14["night_n"]) == ("2026-10-14", 51, 4)
    assert (p14["day"], p14["day_n"]) == (80, 2)
    assert (p15["t"], p15["night"], p15["night_n"]) == ("2026-10-15", 58, 3)
    assert (p15["day"], p15["day_n"]) == (80, 2)
    nights = {n["date"]: n for n in body["nights"]}
    assert nights["2026-10-14"]["source"] == "sleep" and nights["2026-10-15"]["source"] == "fixed"
    # the two overlapping sessions are one interval
    assert len(body["nights"]) == 2
    assert nights["2026-10-14"]["start"].startswith("2026-10-13T21:30")
    assert nights["2026-10-14"]["end"].startswith("2026-10-14T04:30")
    assert body["summary"]["day"]["avg"] == 80 and body["summary"]["night"]["avg"] == 54.5
    assert body["summary"]["night"]["samples"] == 7
    # previous period = 12-13 Oct: only the 22:00 sample of the 13th (day); 23:45 is a night sample
    assert (
        body["previous_summary"]["day"]["avg"] == 80
        and body["previous_summary"]["day"]["days"] == 1
    )
    assert body["previous_summary"]["night"]["avg"] is None

    week = (await web.get("/api/v1/heart/daypart?from=2026-10-14&to=2026-10-15&bucket=week")).json()
    assert [p["t"] for p in week["points"]] == ["2026-10-12"]
    assert week["points"][0]["night_n"] == 7 and week["points"][0]["day_n"] == 4


async def test_deleted_session_falls_back_to_the_fixed_night(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    await _post_two_days(client, auth)
    r = await client.post(
        "/api/v1/ingest/deletions",
        json={
            "device_id": DEVICE,
            "sync_id": "1f9c2f1e-7d2b-4a55-8d1e-2c7e5d9f6a11",
            "items": [
                {"hc_id": "s1", "type": "SleepSession"},
                {"hc_id": "s2", "type": "SleepSession"},
            ],
        },
        headers=auth,
    )
    assert r.status_code == 200, r.text
    body = (await web.get("/api/v1/heart/daypart?from=2026-10-14&to=2026-10-14")).json()
    assert [n["source"] for n in body["nights"]] == ["fixed"]
    # fixed 23:00-07:00 of the 14th: the samples at 23:45, 00:00, 03:00, 06:00 and 06:45
    assert body["points"][0]["night_n"] == 5


async def test_daypart_validation(web: httpx.AsyncClient) -> None:
    r = await web.get("/api/v1/heart/daypart?from=2026-10-15&to=2026-10-14")
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_range"
    assert (await web.get("/api/v1/heart/daypart?bucket=hour")).status_code == 422
    empty = (await web.get("/api/v1/heart/daypart")).json()
    assert empty["points"] == [] and empty["summary"]["day"]["avg"] is None


async def test_seeded_nights_are_lower_and_the_fallback_is_exercised(
    app: FastAPI, settings: Settings, web: httpx.AsyncClient
) -> None:
    cfg = SeedConfig(days=6, seed=5, end_date=TODAY, hr_interval_min=10, unrecorded_nights=(2,))
    await load_synthetic(app.state.sessionmaker, settings, generate(cfg))
    first = TODAY - timedelta(days=4)
    body = (await web.get(f"/api/v1/heart/daypart?from={first}&to={TODAY}")).json()
    sources = [n["source"] for n in body["nights"]]
    assert sources.count("fixed") == 1 and sources.count("sleep") == 4
    for p in body["points"]:
        assert p["night"] is not None and p["day"] is not None and p["night"] < p["day"] - 8
    assert body["summary"]["night"]["avg"] < body["summary"]["day"]["avg"]

"""Overlapping sources must never be summed blindly; official aggregates stay separate."""

import httpx
import pytest
from fastapi import FastAPI

from app.services.daily import Coverage, rank_sources
from tests.helpers import DEVICE, SYNC, computed, post, post_records, record, steps

DAY = "2026-10-14"


def test_coverage_merges_and_measures_overlap() -> None:
    c = Coverage()
    c.add_all([(0, 10), (5, 15), (20, 30)])
    assert c.overlap(0, 100) == 25
    assert c.overlap(12, 22) == 5
    assert c.overlap(16, 19) == 0
    assert c.covers_point(7) and not c.covers_point(0) and not c.covers_point(17)


def test_rank_sources_priority_then_volume() -> None:
    assert rank_sources({"a": 10, "b": 50, "c": 30}, []) == {"b": 0, "c": 1, "a": 2}
    assert rank_sources({"a": 10, "b": 50, "c": 30}, ["a"]) == {"a": 0, "b": 1, "c": 2}


async def test_identical_overlapping_sources_are_not_double_counted(
    client: httpx.AsyncClient, auth: dict[str, str], app: FastAPI
) -> None:
    a = ("2026-10-14T08:00:00+02:00", "2026-10-14T08:15:00+02:00")
    await post_records(
        client, auth,
        [steps("fit", *a, 1000, pkg="fit"), steps("feelfit", *a, 900, pkg="feelfit"),
         steps("withings", *a, 1000, pkg="withings")],
    )
    row = await computed(app, "Steps", DAY)
    assert row[0] == 1000
    by_source = row[5]["by_source"]
    assert by_source["feelfit"]["counted"] == 0
    assert sum(v["counted"] for v in by_source.values()) == 1000


async def test_partial_overlap_counts_only_the_uncovered_share(
    client: httpx.AsyncClient, auth: dict[str, str], app: FastAPI
) -> None:
    await post_records(
        client, auth,
        [steps("phone", "2026-10-14T08:00:00+02:00", "2026-10-14T08:15:00+02:00", 1000, pkg="phone"),
         # watch covers 08:07:30-08:22:30: half of it overlaps the phone
         steps("watch", "2026-10-14T08:07:30+02:00", "2026-10-14T08:22:30+02:00", 600, pkg="watch")],
    )
    assert (await computed(app, "Steps", DAY))[0] == pytest.approx(1000 + 300)


async def test_disjoint_sources_add_up(
    client: httpx.AsyncClient, auth: dict[str, str], app: FastAPI
) -> None:
    await post_records(
        client, auth,
        [steps("phone", "2026-10-14T08:00:00+02:00", "2026-10-14T08:15:00+02:00", 1000, pkg="phone"),
         steps("watch", "2026-10-14T09:00:00+02:00", "2026-10-14T09:15:00+02:00", 500, pkg="watch")],
    )
    assert (await computed(app, "Steps", DAY))[0] == 1500


async def test_configured_priority_beats_data_volume(
    client: httpx.AsyncClient, auth: dict[str, str], app: FastAPI, settings
) -> None:
    settings.source_priority = "watch, phone"
    a = ("2026-10-14T08:00:00+02:00", "2026-10-14T08:15:00+02:00")
    await post_records(
        client, auth, [steps("p", *a, 1000, pkg="phone"), steps("w", *a, 900, pkg="watch")]
    )
    assert (await computed(app, "Steps", DAY))[0] == 900


async def test_official_aggregates_are_stored_apart_and_idempotent(
    client: httpx.AsyncClient, auth: dict[str, str], app: FastAPI
) -> None:
    a = ("2026-10-14T08:00:00+02:00", "2026-10-14T08:15:00+02:00")
    await post_records(client, auth, [steps("fit", *a, 1000, pkg="fit")])

    def body(value: float, snapshot: str) -> dict:
        return {"device_id": DEVICE, "sync_id": SYNC, "items": [
            {"date": DAY, "type": "Steps", "sum": value, "data_origins": ["fit"],
             "snapshot_at": snapshot},
            {"date": DAY, "type": "SleepSession", "sum": 26340},
            {"date": DAY, "type": "Steps"},  # no stats: rejected
            {"date": DAY, "type": "Nope", "sum": 1},
        ]}

    r1 = (await post(client, auth, "daily-aggregates", body(1200, "2026-10-14T20:00:00Z"))).json()
    assert (r1["received"], r1["upserted"], r1["unchanged"], len(r1["rejected"])) == (4, 2, 0, 2)
    assert {x["reason"] for x in r1["rejected"]} == {"invalid_record", "unsupported_type"}

    # both views coexist; the computed one is untouched by the snapshot
    assert (await computed(app, "Steps", DAY, "hc_official"))[0] == 1200
    assert (await computed(app, "Steps", DAY, "computed"))[0] == 1000
    assert (await computed(app, "SleepSession", DAY, "hc_official"))[0] == 26340

    same = (await post(client, auth, "daily-aggregates", body(1200, "2026-10-14T20:00:00Z"))).json()
    assert same["upserted"] == 0 and same["unchanged"] == 2

    stale = (await post(client, auth, "daily-aggregates", body(5, "2026-10-14T10:00:00Z"))).json()
    assert stale["upserted"] == 0
    assert (await computed(app, "Steps", DAY, "hc_official"))[0] == 1200

    newer = (await post(client, auth, "daily-aggregates", body(1300, "2026-10-14T23:00:00Z"))).json()
    assert newer["upserted"] == 1
    assert (await computed(app, "Steps", DAY, "hc_official"))[0] == 1300


async def test_sleep_sessions_from_two_sources_count_once(
    client: httpx.AsyncClient, auth: dict[str, str], app: FastAPI
) -> None:
    stages = [
        {"stage": "light", "start_time": "2026-10-13T23:00:00+02:00", "end_time": "2026-10-14T02:00:00+02:00"},
        {"stage": "awake", "start_time": "2026-10-14T02:00:00+02:00", "end_time": "2026-10-14T02:30:00+02:00"},
        {"stage": "deep", "start_time": "2026-10-14T02:30:00+02:00", "end_time": "2026-10-14T06:30:00+02:00"},
    ]
    watch = record("SleepSession", "w", "2026-10-13T23:00:00+02:00", "2026-10-14T06:30:00+02:00",
                   {"stages": stages}, pkg="watch")
    phone = record("SleepSession", "p", "2026-10-13T23:10:00+02:00", "2026-10-14T06:20:00+02:00",
                   {}, pkg="phone")
    await post_records(client, auth, [watch, phone])
    row = await computed(app, "SleepSession", DAY)
    assert row[0] == (3 + 4) * 3600  # awake time excluded, phone duplicate dropped
    assert row[4] == 1
    assert row[5]["stages_s"]["awake"] == 1800


async def test_same_weight_mirrored_by_two_apps_counts_once(
    client: httpx.AsyncClient, auth: dict[str, str], app: FastAPI
) -> None:
    t = "2026-10-14T07:10:00+02:00"
    await post_records(
        client, auth,
        [record("Weight", "a", t, None, {"value": 78.0}, pkg="scale"),
         record("Weight", "b", t, None, {"value": 78.0}, pkg="phone"),
         record("Weight", "c", "2026-10-14T21:00:00+02:00", None, {"value": 79.0}, pkg="scale")],
    )
    row = await computed(app, "Weight", DAY)
    assert row[4] == 2  # count
    assert row[1] == pytest.approx(78.5) and row[2] == 78.0 and row[3] == 79.0
    assert row[5]["last"]["value"] == 79.0


async def test_heart_rate_daily_stats_and_exercise_dedupe(
    client: httpx.AsyncClient, auth: dict[str, str], app: FastAPI
) -> None:
    hr = record("HeartRate", "hr", "2026-10-14T10:00:00+02:00", "2026-10-14T10:10:00+02:00",
                {"samples": [{"time": f"2026-10-14T10:0{i}:00+02:00", "value": v}
                             for i, v in enumerate([50, 70, 90])]})
    walk = ("2026-10-14T18:00:00+02:00", "2026-10-14T18:30:00+02:00")
    await post_records(
        client, auth,
        [hr,
         record("ExerciseSession", "e1", *walk, {"exercise_type": "WALKING"}, pkg="watch"),
         record("ExerciseSession", "e2", *walk, {"exercise_type": "WALKING"}, pkg="phone")],
    )
    row = await computed(app, "HeartRate", DAY)
    assert (row[1], row[2], row[3], row[4]) == (70, 50, 90, 3)
    ex = await computed(app, "ExerciseSession", DAY)
    assert ex[0] == 1800 and ex[4] == 1

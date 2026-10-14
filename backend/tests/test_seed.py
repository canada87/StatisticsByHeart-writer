"""The synthetic generator produces valid, idempotent, de-duplicated data."""

from datetime import date

import httpx
from fastapi import FastAPI

from app.config import Settings
from app.seed.loader import load_synthetic
from app.seed.synthetic import PHONE, WATCH, SeedConfig, generate
from tests.helpers import computed, rows, scalar

CFG = SeedConfig(
    days=3, seed=7, end_date=date(2026, 10, 25), hr_interval_min=10
)  # spans DST change


def test_generator_is_deterministic_and_contract_shaped() -> None:
    a, b = generate(CFG), generate(CFG)
    assert a.records == b.records and a.aggregates == b.aggregates
    assert {r["type"] for r in a.records} >= {
        "Steps",
        "HeartRate",
        "SleepSession",
        "ExerciseSession",
        "Weight",
        "RestingHeartRate",
    }
    offsets = {r["start_offset_s"] for r in a.records}
    assert offsets == {3600, 7200} or offsets <= {3600, 7200}


async def test_seed_loads_cleanly_twice_without_duplicates(
    app: FastAPI, settings: Settings
) -> None:
    data = generate(CFG)
    first = await load_synthetic(app.state.sessionmaker, settings, data)
    assert first["rejected"] == 0 and first["records"] == len(data.records)
    count = await scalar(app, "SELECT count(*) FROM health_record")
    samples = await scalar(app, "SELECT count(*) FROM health_sample")
    assert count == len(data.records)

    second = await load_synthetic(app.state.sessionmaker, settings, data)
    assert second["records"] == 0 and second["aggregates"] == 0
    assert await scalar(app, "SELECT count(*) FROM health_record") == count
    assert await scalar(app, "SELECT count(*) FROM health_sample") == samples


async def test_seeded_dedupe_matches_the_single_source_truth(
    app: FastAPI, settings: Settings, client: httpx.AsyncClient
) -> None:
    data = generate(CFG)
    await load_synthetic(app.state.sessionmaker, settings, data)
    day = "2026-10-24"
    phone_total = sum(
        r["data"]["value"]
        for r in data.records
        if r["type"] == "Steps"
        and r["source"]["package"] == PHONE
        and r["start_time"].startswith(day)
    )
    watch_total = sum(
        r["data"]["value"]
        for r in data.records
        if r["type"] == "Steps"
        and r["source"]["package"] == WATCH
        and r["start_time"].startswith(day)
    )
    row = await computed(app, "Steps", day)
    # phone and watch cover the very same quarter-hours: the result is one source plus the
    # (few) quarter-hours only the other one has, never the sum of both
    assert row[0] < phone_total + watch_total
    assert row[0] >= max(phone_total, watch_total)
    official = await computed(app, "Steps", day, "hc_official")
    assert official[0] == phone_total
    # one sleep session per night survives de-duplication
    assert (await computed(app, "SleepSession", day))[4] == 1
    assert len(await rows(app, "SELECT 1 FROM health_record WHERE type='SleepSession'")) == 6

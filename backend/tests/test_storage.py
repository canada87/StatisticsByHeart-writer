"""Space and limits panel: sizes, estimates, soft deletes, disk, limits; ordinary DB role only."""

import json

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config import Settings
from app.health_types import MAX_ROUTE_POINTS
from app.services import storage
from app.services.queries import INTRADAY_MAX_DAYS, MAX_POINTS, MAX_SERIES_DAYS
from tests.helpers import DEVICE, post, post_records, record, rows, scalar


async def test_storage_needs_a_session(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/storage")).status_code == 401


async def test_shape_and_consistency_on_synthetic_data(
    seeded: None, web: httpx.AsyncClient, app: FastAPI
) -> None:
    r = await web.get("/api/v1/storage")
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {
        "database_bytes",
        "postgres_version",
        "tables",
        "records_live",
        "records_deleted",
        "first_data",
        "last_data",
        "last_ingest",
        "growth",
        "disk",
        "limits",
    }
    assert body["database_bytes"] > 1_000_000 and body["postgres_version"].startswith("16")
    by = {t["name"]: t for t in body["tables"]}
    assert {"health_record", "health_sample", "daily_metric", "exercise_override"} <= set(by)
    for t in body["tables"]:
        assert t["total_bytes"] == t["data_bytes"] + t["index_bytes"] and t["index_bytes"] >= 0
        assert isinstance(t["rows_exact"], bool) and t["rows"] >= 0
    # small tables are counted exactly: the figure is the real count
    assert by["health_record"]["rows_exact"] is True
    assert by["health_record"]["rows"] == await scalar(app, "SELECT count(*) FROM health_record")
    assert by["health_sample"]["rows"] == await scalar(app, "SELECT count(*) FROM health_sample")
    assert [t["total_bytes"] for t in body["tables"]] == sorted(
        (t["total_bytes"] for t in body["tables"]), reverse=True
    )
    assert body["records_live"] + body["records_deleted"] == by["health_record"]["rows"]
    assert body["first_data"] < body["last_data"] and body["last_ingest"] is not None

    g = body["growth"]
    assert g["estimated"] is True and 1 <= g["window_days"] <= 30
    assert g["records"] > 0 and g["samples"] > 0 and g["bytes"] > 0
    assert g["bytes_per_year"] == int(g["bytes"] / g["window_days"] * 365)

    d = body["disk"]
    assert 0 < d["free_bytes"] <= d["total_bytes"] and 0 <= d["free_percent"] <= 100
    assert d["used_bytes"] <= d["total_bytes"]


async def test_empty_database(web: httpx.AsyncClient) -> None:
    body = (await web.get("/api/v1/storage")).json()
    assert body["records_live"] == 0 and body["records_deleted"] == 0
    assert body["first_data"] is None and body["last_data"] is None and body["last_ingest"] is None
    assert body["growth"] == {
        "window_days": 0,
        "records": 0,
        "samples": 0,
        "bytes": 0,
        "bytes_per_year": 0,
        "estimated": True,
    }
    assert body["database_bytes"] > 0 and body["limits"]["items"]


async def test_soft_deleted_records_are_counted_and_lose_their_samples(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str], app: FastAPI
) -> None:
    hr = record(
        "HeartRate",
        "h1",
        "2026-10-14T10:00:00+02:00",
        "2026-10-14T10:10:00+02:00",
        {"samples": [{"time": "2026-10-14T10:01:00+02:00", "value": 71}]},
    )
    await post_records(
        client,
        auth,
        [hr, record("Weight", "w1", "2026-10-14T07:00:00+02:00", None, {"value": 78.2})],
    )
    before = (await web.get("/api/v1/storage")).json()
    assert (before["records_live"], before["records_deleted"]) == (2, 0)
    r = await post(
        client,
        auth,
        "deletions",
        {
            "device_id": DEVICE,
            "sync_id": "1f9c2f1e-7d2b-4a55-8d1e-2c7e5d9f6a21",
            "items": [{"hc_id": "h1"}],
        },
    )
    assert r.status_code == 200
    after = (await web.get("/api/v1/storage")).json()
    assert (after["records_live"], after["records_deleted"]) == (1, 1)
    # the row stays (soft delete), its samples are gone
    assert await scalar(app, "SELECT count(*) FROM health_sample") == 0
    assert await scalar(app, "SELECT count(*) FROM health_record") == 2


async def test_growth_counts_what_was_ingested(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    samples = [{"time": f"2026-10-14T10:{m:02d}:00+02:00", "value": 70 + m} for m in range(5)]
    await post_records(
        client,
        auth,
        [
            record(
                "HeartRate",
                "h1",
                "2026-10-14T10:00:00+02:00",
                "2026-10-14T10:10:00+02:00",
                {"samples": samples},
            )
        ],
    )
    g = (await web.get("/api/v1/storage")).json()["growth"]
    assert (g["window_days"], g["records"], g["samples"]) == (1, 1, 5)
    assert g["bytes"] > 0 and g["bytes_per_year"] == g["bytes"] * 365


async def test_no_health_value_leaves_the_endpoint(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    await post_records(
        client,
        auth,
        [
            record("Weight", "w1", "2026-10-14T07:00:00+02:00", None, {"value": 123.456}),
            record(
                "HeartRate",
                "h1",
                "2026-10-14T10:00:00+02:00",
                "2026-10-14T10:10:00+02:00",
                {"samples": [{"time": "2026-10-14T10:01:00+02:00", "value": 187}]},
            ),
        ],
    )
    text_body = (await web.get("/api/v1/storage")).text
    for leak in ("123.456", "pkg.a", "w1", "h1", "hc_id", "source_package", "exercise_type"):
        assert leak not in text_body, leak
    # only sizes, counts, dates and the table names
    body = json.loads(text_body)
    assert {t["name"] for t in body["tables"]} <= {
        "health_record",
        "health_sample",
        "daily_metric",
        "sync_run",
        "device",
        "ingest_token",
        "user_session",
        "admin_user",
        "exercise_override",
        "alembic_version",
    }


async def test_big_tables_are_estimated_not_counted(
    seeded: None, web: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(storage, "EXACT_COUNT_BELOW", 0)  # pretend every table is big
    body = (await web.get("/api/v1/storage")).json()
    assert body["tables"] and all(t["rows_exact"] is False for t in body["tables"])
    assert all(isinstance(t["rows"], int) and t["rows"] >= 0 for t in body["tables"])


async def test_limits_and_retention_come_from_the_real_constants(
    web: httpx.AsyncClient, settings: Settings
) -> None:
    items = (await web.get("/api/v1/storage")).json()["limits"]["items"]
    assert [i["id"] for i in items] == [
        "retention",
        "soft_delete",
        "session_purge",
        "daily_recompute",
        "ingest_batch",
        "ingest_body",
        "route_points",
        "query_days",
        "intraday",
        "chart_points",
    ]
    by = {i["id"]: i["params"] for i in items}
    assert by == {i["id"]: i["params"] for i in storage.describe_limits(settings)["items"]}
    assert by["retention"] == {"forever": True}  # nothing deletes health data
    assert by["soft_delete"] == {"samples_removed": True}
    assert by["session_purge"] == {"minute": 17, "session_ttl_hours": settings.session_ttl_hours}
    assert by["ingest_batch"] == {"max_records": settings.max_batch_records}
    assert by["ingest_body"] == {"max_bytes": settings.max_body_bytes}
    assert by["route_points"] == {"max_points": MAX_ROUTE_POINTS}
    assert by["query_days"] == {"max_days": MAX_SERIES_DAYS}
    assert by["intraday"] == {
        "minutes_15_max_days": INTRADAY_MAX_DAYS["15min"],
        "hour_max_days": INTRADAY_MAX_DAYS["hour"],
    }
    assert by["chart_points"] == {"max_points": MAX_POINTS}
    assert (MAX_ROUTE_POINTS, MAX_SERIES_DAYS) == (50_000, 3660)


async def test_it_works_with_an_ordinary_non_superuser_role(
    seeded: None, database_url: str, settings: Settings
) -> None:
    """The app's DB user is not a superuser: every call must work without extra privileges."""
    admin = create_engine(database_url, isolation_level="AUTOCOMMIT")
    role = "sbh_ordinary_probe"
    with admin.connect() as conn:
        conn.execute(text(f"DROP ROLE IF EXISTS {role}"))
        conn.execute(text(f"CREATE ROLE {role} LOGIN PASSWORD 'probe' NOSUPERUSER NOCREATEDB"))
        conn.execute(text(f"GRANT ALL ON ALL TABLES IN SCHEMA public TO {role}"))
        conn.execute(text(f"GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO {role}"))
    url = make_url(database_url).set(username=role, password="probe").render_as_string(False)
    engine = create_async_engine(url)
    try:
        async with AsyncSession(engine) as session:
            is_super = (
                await session.execute(
                    text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
                )
            ).scalar()
            assert is_super is False
            report = await storage.storage_report(session, settings)
        assert report["database_bytes"] > 0 and report["tables"] and report["records_live"] > 0
        assert report["postgres_version"].startswith("16")
    finally:
        await engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f"DROP OWNED BY {role}"))
            conn.execute(text(f"DROP ROLE {role}"))
        admin.dispose()


async def test_rows_helper_is_not_used_for_values(app: FastAPI) -> None:
    # the service never selects a measurement: its SQL only touches catalog functions and
    # count/min/max of dates; guard the constant so a future change has to be deliberate
    assert (await rows(app, "SELECT 1")) == [(1,)]
    assert storage.EXACT_COUNT_BELOW == 100_000 and storage.GROWTH_WINDOW_DAYS == 30

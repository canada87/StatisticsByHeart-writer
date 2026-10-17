"""Space used by the data, DB limits and retention (read-only, ordinary DB role, no health values).

Everything here is counts, sizes and dates; it never selects a measurement. Sizes come from the
Postgres catalog functions every role may call on its own tables. Row counts are the catalog
estimate for big tables and an exact ``count(*)`` only where that is cheap (below
``EXACT_COUNT_BELOW`` estimated rows); every table says which one it is.
"""

from __future__ import annotations

import shutil
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import table

from app.config import Settings
from app.health_types import MAX_ROUTE_POINTS
from app.models import HealthRecord
from app.scheduler import PURGE_SESSIONS_MINUTE, RECONCILE_HOUR, RECONCILE_MINUTE
from app.services.queries import INTRADAY_MAX_DAYS, MAX_POINTS, MAX_SERIES_DAYS

EXACT_COUNT_BELOW = 100_000
"""Tables estimated below this many rows are counted exactly (cheap); bigger ones stay estimated."""

GROWTH_WINDOW_DAYS = 30
"""Growth is measured over the last 30 complete days of DATA (fewer if the history is shorter)."""

_TABLES = text(
    """
    SELECT s.relname AS name,
           pg_total_relation_size(s.relid) AS total_bytes,
           pg_indexes_size(s.relid) AS index_bytes,
           s.n_live_tup AS live_estimate,
           c.reltuples::bigint AS planner_estimate
    FROM pg_stat_user_tables s
    JOIN pg_class c ON c.oid = s.relid
    ORDER BY pg_total_relation_size(s.relid) DESC, s.relname
    """
)

_IN_WINDOW = text(
    """
    SELECT count(*) AS records,
           coalesce(sum(coalesce((data->>'sample_count')::bigint, 0)), 0) AS samples,
           min(local_date) AS first_day
    FROM health_record
    WHERE deleted_at IS NULL AND local_date >= :lo AND local_date <= :hi
    """
)


async def _tables(session: AsyncSession) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in (await session.execute(_TABLES)).mappings():
        estimate = max(int(r["live_estimate"] or 0), int(r["planner_estimate"] or 0), 0)
        exact = estimate < EXACT_COUNT_BELOW
        rows = estimate
        if exact:
            # the name comes from the catalog and is quoted by SQLAlchemy
            counted = await session.execute(select(func.count()).select_from(table(r["name"])))
            rows = int(counted.scalar() or 0)
        total, index = int(r["total_bytes"]), int(r["index_bytes"])
        out.append(
            {
                "name": r["name"],
                "total_bytes": total,
                "index_bytes": index,
                "data_bytes": total - index,
                "rows": rows,
                "rows_exact": exact,
            }
        )
    return out


def _bytes_per_row(tables: list[dict[str, Any]], name: str) -> float:
    for t in tables:
        if t["name"] == name and t["rows"] > 0:
            return float(int(t["total_bytes"]) / int(t["rows"]))
    return 0.0


async def _growth(
    session: AsyncSession, tables: list[dict[str, Any]], today: date
) -> dict[str, Any]:
    """Growth per month/year from the TIME OF THE DATA, not from when it was ingested.

    Records (and their series samples) whose local day falls in the last 30 complete days
    (today excluded: it is partial) times the average size of a row of their table, scaled to a
    month and to a year. A backfill (years of old data ingested in a day) therefore changes
    nothing. If the history is shorter than 30 days the real length is used and flagged.
    An ESTIMATE: it ignores index/bloat growth beyond the average row size.
    """
    yesterday = today - timedelta(days=1)
    first = (
        await session.execute(
            select(func.min(HealthRecord.local_date)).where(HealthRecord.deleted_at.is_(None))
        )
    ).scalar()
    empty = {
        "window_days": 0,
        "records": 0,
        "samples": 0,
        "bytes": 0,
        "bytes_per_month": 0,
        "bytes_per_year": 0,
        "partial_history": False,
        "estimated": True,
    }
    if first is None or first > yesterday:
        return empty
    lo = max(first, yesterday - timedelta(days=GROWTH_WINDOW_DAYS - 1))
    window = (yesterday - lo).days + 1
    row = (await session.execute(_IN_WINDOW, {"lo": lo, "hi": yesterday})).one()
    records, samples = int(row.records), int(row.samples)
    size = int(
        records * _bytes_per_row(tables, "health_record")
        + samples * _bytes_per_row(tables, "health_sample")
    )
    return {
        "window_days": window,
        "records": records,
        "samples": samples,
        "bytes": size,
        "bytes_per_month": int(size / window * 30),
        "bytes_per_year": int(size / window * 365),
        "partial_history": window < GROWTH_WINDOW_DAYS,
        "estimated": True,
    }


def describe_limits(settings: Settings) -> dict[str, Any]:
    """Limits and retention, from the real constants and settings (the page only words them)."""
    return {
        "items": [
            {"id": "retention", "params": {"forever": True}},
            {"id": "soft_delete", "params": {"samples_removed": True}},
            {
                "id": "session_purge",
                "params": {
                    "minute": PURGE_SESSIONS_MINUTE,
                    "session_ttl_hours": settings.session_ttl_hours,
                },
            },
            {
                "id": "daily_recompute",
                "params": {"hour": RECONCILE_HOUR, "minute": RECONCILE_MINUTE},
            },
            {"id": "stale_alarm", "params": {"threshold_hours": settings.stale_hours}},
            {"id": "ingest_batch", "params": {"max_records": settings.max_batch_records}},
            {"id": "ingest_body", "params": {"max_bytes": settings.max_body_bytes}},
            {"id": "route_points", "params": {"max_points": MAX_ROUTE_POINTS}},
            {"id": "query_days", "params": {"max_days": MAX_SERIES_DAYS}},
            {
                "id": "intraday",
                "params": {
                    "minutes_15_max_days": INTRADAY_MAX_DAYS["15min"],
                    "hour_max_days": INTRADAY_MAX_DAYS["hour"],
                },
            },
            {"id": "chart_points", "params": {"max_points": MAX_POINTS}},
        ]
    }


async def storage_report(session: AsyncSession, settings: Settings) -> dict[str, Any]:
    tables = await _tables(session)
    db_bytes = int(
        (await session.execute(text("SELECT pg_database_size(current_database())"))).scalar() or 0
    )
    version = str((await session.execute(text("SHOW server_version"))).scalar() or "")
    live = int(
        (
            await session.execute(
                select(func.count())
                .select_from(HealthRecord)
                .where(HealthRecord.deleted_at.is_(None))
            )
        ).scalar()
        or 0
    )
    deleted = int(
        (
            await session.execute(
                select(func.count())
                .select_from(HealthRecord)
                .where(HealthRecord.deleted_at.is_not(None))
            )
        ).scalar()
        or 0
    )
    first, last, last_ingest = (
        await session.execute(
            select(
                func.min(HealthRecord.start_ts).filter(HealthRecord.deleted_at.is_(None)),
                func.max(func.coalesce(HealthRecord.end_ts, HealthRecord.start_ts)).filter(
                    HealthRecord.deleted_at.is_(None)
                ),
                func.max(HealthRecord.ingested_at),
            )
        )
    ).one()
    usage = shutil.disk_usage("/")
    return {
        "database_bytes": db_bytes,
        "postgres_version": version,
        "tables": tables,
        "records_live": live,
        "records_deleted": deleted,
        "first_data": first,
        "last_data": last,
        "last_ingest": last_ingest,
        "growth": await _growth(session, tables, datetime.now(settings.tz).date()),
        "disk": {
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
            "free_percent": round(usage.free / usage.total * 100, 1) if usage.total else 0.0,
        },
        "limits": describe_limits(settings),
    }

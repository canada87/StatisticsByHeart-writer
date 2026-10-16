"""Housekeeping jobs shared by the scheduler and the CLI."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete, func, or_, select, union
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import DailyMetric, HealthRecord, UserSession
from app.services.daily import recompute_days
from app.services.ingest import INGEST_LOCK_KEY

log = logging.getLogger("sbh.maintenance")


async def recompute_range(
    session: AsyncSession, settings: Settings, first: date, last: date
) -> int:
    """Recompute computed daily metrics for every (type, day) with data or a stale row in range.

    Needed after changing SBH_SOURCE_PRIORITY, and run nightly as a self-healing pass.
    """
    await session.execute(select(func.pg_advisory_xact_lock(INGEST_LOCK_KEY)))
    live = select(HealthRecord.type, HealthRecord.local_date).where(
        HealthRecord.deleted_at.is_(None), HealthRecord.local_date.between(first, last)
    )
    stale = select(DailyMetric.type, DailyMetric.local_date).where(
        DailyMetric.source == "computed", DailyMetric.local_date.between(first, last)
    )
    pairs = (await session.execute(union(live, stale))).all()
    written = await recompute_days(session, [(t, d) for t, d in pairs], settings)
    await session.commit()
    log.info("recompute range=%s..%s pairs=%d written=%d", first, last, len(pairs), written)
    return written


async def recompute_recent(session: AsyncSession, settings: Settings, days: int = 3) -> int:
    today = datetime.now(settings.tz).date()
    return await recompute_range(session, settings, today - timedelta(days=days), today)


async def purge_sessions(session: AsyncSession) -> int:
    cutoff = datetime.now(UTC) - timedelta(days=1)
    result = await session.execute(
        delete(UserSession).where(
            or_(UserSession.expires_at < cutoff, UserSession.revoked_at < cutoff)
        )
    )
    await session.commit()
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


HEART_POINTS_CHUNK_DAYS = 30


async def recompute_heart_points(
    session: AsyncSession,
    settings: Settings,
    first: date | None = None,
    last: date | None = None,
    *,
    only_missing: bool = False,
) -> int:
    """Recompute the Heart Points of every day with heart-rate or step data (the whole history).

    ``only_missing`` skips days already computed with the current HRmax settings: that is what runs
    at startup. Without it, every day is redone (first deploy, or after changing the birth year /
    HRmax). Works in chunks, one commit each, and logs only counts.
    """
    from app.services import heartpoints

    if only_missing:
        days = await heartpoints.days_to_compute(session, settings)
    else:
        days = sorted(
            {
                d
                for (d,) in (
                    await session.execute(
                        select(HealthRecord.local_date)
                        .where(
                            HealthRecord.type.in_(("HeartRate", "Steps")),
                            HealthRecord.deleted_at.is_(None),
                        )
                        .distinct()
                    )
                ).all()
            }
        )
    days = [d for d in days if (first is None or d >= first) and (last is None or d <= last)]
    written = 0
    for i in range(0, len(days), HEART_POINTS_CHUNK_DAYS):
        await session.execute(select(func.pg_advisory_xact_lock(INGEST_LOCK_KEY)))
        written += await heartpoints.recompute(
            session, settings, days[i : i + HEART_POINTS_CHUNK_DAYS]
        )
        await session.commit()
    log.info("heart points: %d days computed (of %d candidates)", written, len(days))
    return written

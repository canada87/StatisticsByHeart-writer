"""The "sync stalled" alarm: the same answer for Home Assistant and for the dashboard.

A sync counts as successful when it ended ``completed`` or ``partial`` (the phone delivered, a few
records may have been refused). The alarm looks at the last successful sync of ANY device: with two
phones, the stale one does not raise it while the other keeps syncing. Only dates and counts: no
health value.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import SyncRun

SUCCESS_STATUSES = ("completed", "partial")


async def last_success_per_device(session: AsyncSession) -> dict[uuid.UUID, datetime]:
    rows = (
        await session.execute(
            select(SyncRun.device_id, func.max(SyncRun.finished_at))
            .where(SyncRun.status.in_(SUCCESS_STATUSES), SyncRun.finished_at.is_not(None))
            .group_by(SyncRun.device_id)
        )
    ).all()
    return {d: t for d, t in rows if t is not None}


def evaluate(
    last_sync_at: datetime | None, threshold_hours: float, now: datetime
) -> tuple[str, float | None]:
    """("never" | "ok" | "stale", hours since the last successful sync).

    Stale only when MORE than the threshold has passed: exactly 6 h is still ok.
    """
    if last_sync_at is None:
        return "never", None
    hours = (now - last_sync_at).total_seconds() / 3600
    return ("stale" if hours > threshold_hours else "ok"), hours


async def alarm_state(
    session: AsyncSession, settings: Settings, now: datetime | None = None
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    last_sync = (
        await session.execute(
            select(func.max(SyncRun.finished_at)).where(SyncRun.status.in_(SUCCESS_STATUSES))
        )
    ).scalar()
    last_activity = (await session.execute(select(func.max(SyncRun.last_activity_at)))).scalar()
    status, hours = evaluate(last_sync, settings.stale_hours, now)
    return {
        "status": status,
        "last_sync_at": last_sync,
        "last_ingest_at": last_activity,
        "hours_since_sync": None if hours is None else round(hours, 2),
        "threshold_hours": settings.stale_hours,
    }

"""In-process periodic jobs (APScheduler). Single process on purpose: no Celery/Redis."""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI

from app.services import maintenance

log = logging.getLogger("sbh.scheduler")

PURGE_SESSIONS_MINUTE = 17
"""Expired web sessions are purged at this minute of every hour (the only cleanup there is)."""

RECONCILE_HOUR, RECONCILE_MINUTE = 3, 30
"""Daily metrics of the last days are recomputed every night at this time (not a retention)."""


def build_scheduler(app: FastAPI) -> AsyncIOScheduler:
    settings = app.state.settings
    scheduler = AsyncIOScheduler(timezone=settings.tz)

    async def purge() -> None:
        async with app.state.sessionmaker() as session:
            n = await maintenance.purge_sessions(session)
            log.info("purged %d expired sessions", n)

    async def reconcile() -> None:
        async with app.state.sessionmaker() as session:
            await maintenance.recompute_recent(session, settings)

    scheduler.add_job(
        purge, CronTrigger(minute=PURGE_SESSIONS_MINUTE), id="purge_sessions", coalesce=True
    )
    scheduler.add_job(
        reconcile,
        CronTrigger(hour=RECONCILE_HOUR, minute=RECONCILE_MINUTE),
        id="reconcile_daily",
        coalesce=True,
    )
    return scheduler

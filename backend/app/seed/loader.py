"""Load synthetic data through the same service layer the API uses."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.schemas import DailyAggregatesBatch, RecordsBatch, SyncReport
from app.seed.synthetic import NAMESPACE, SEED_DEVICE_ID, SyntheticData, chunked
from app.services import ingest as svc


async def load_synthetic(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    data: SyntheticData,
    *,
    token_id: uuid.UUID | None = None,
    batch_size: int = 500,
    second_device: bool = False,
) -> dict[str, int]:
    started = datetime.now(UTC)
    sync_id = uuid.uuid4()
    base = {"device_id": str(SEED_DEVICE_ID), "sync_id": str(sync_id)}
    totals = {"records": 0, "rejected": 0, "aggregates": 0}

    for chunk in chunked(data.records, batch_size):
        batch = RecordsBatch.model_validate({**base, "records": chunk})
        async with sessionmaker() as session:
            result = await svc.ingest_records(session, settings, token_id, batch)
            await session.commit()
        totals["records"] += result.upserted
        totals["rejected"] += len(result.rejected)

    for chunk in chunked(data.aggregates, batch_size):
        agg = DailyAggregatesBatch.model_validate({**base, "items": chunk})
        async with sessionmaker() as session:
            agg_result = await svc.ingest_daily_aggregates(session, settings, token_id, agg)
            await session.commit()
        totals["aggregates"] += agg_result.upserted

    report = SyncReport.model_validate(
        {
            **base,
            "device": {"name": "Synthetic seed", "app_version": "seed"},
            "mode": "backfill",
            "status": "completed" if not totals["rejected"] else "partial",
            "started_at": started.isoformat(),
            "counts": totals,
        }
    )
    async with sessionmaker() as session:
        await svc.ingest_sync_report(session, token_id, report)
        await session.commit()
    if second_device:
        await _second_device_sync(sessionmaker, token_id)
    return totals


async def _second_device_sync(
    sessionmaker: async_sessionmaker[AsyncSession], token_id: uuid.UUID | None
) -> None:
    """A second phone that synced two hours ago (a small delivery, no health data of its own)."""
    finished = datetime.now(UTC) - timedelta(hours=2)
    report = SyncReport.model_validate(
        {
            "device_id": str(uuid.uuid5(NAMESPACE, "device-2")),
            "sync_id": str(uuid.uuid5(NAMESPACE, "device-2-sync")),
            "device": {"name": "Synthetic seed (second phone)", "app_version": "seed"},
            "mode": "incremental",
            "status": "completed",
            "started_at": (finished - timedelta(minutes=1)).isoformat(),
            "finished_at": finished.isoformat(),
            "counts": {"records": 0, "rejected": 0, "aggregates": 0},
        }
    )
    async with sessionmaker() as session:
        await svc.ingest_sync_report(session, token_id, report)
        await session.commit()

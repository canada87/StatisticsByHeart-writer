"""Load synthetic data through the same service layer the API uses."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.schemas import DailyAggregatesBatch, RecordsBatch, SyncReport
from app.seed.synthetic import SEED_DEVICE_ID, SyntheticData, chunked
from app.services import ingest as svc


async def load_synthetic(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    data: SyntheticData,
    *,
    token_id: uuid.UUID | None = None,
    batch_size: int = 500,
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
    return totals

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.config import Settings
from app.deps import Db, IngestAuth, SettingsDep
from app.errors import ApiError
from app.schemas import (
    DailyAggregatesBatch,
    DailyAggregatesResult,
    DeletionsBatch,
    DeletionsResult,
    ErrorResponse,
    RecordsBatch,
    RecordsResult,
    SyncReport,
    SyncReportResult,
)
from app.services import ingest as svc

router = APIRouter(prefix="/api/v1/ingest", tags=["ingest"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse},
    413: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}


def _check_size(n: int, settings: Settings) -> None:
    if n > settings.max_batch_records:
        raise ApiError(
            413,
            "batch_too_large",
            f"At most {settings.max_batch_records} items per request (got {n})",
        )


@router.post(
    "/records",
    response_model=RecordsResult,
    summary="Upsert Health Connect records (idempotent)",
    responses=_ERRORS,
)
async def ingest_records(
    batch: RecordsBatch, token: IngestAuth, session: Db, settings: SettingsDep
) -> RecordsResult:
    _check_size(len(batch.records), settings)
    result = await svc.ingest_records(session, settings, token.id, batch)
    await session.commit()
    return result


@router.post(
    "/deletions",
    response_model=DeletionsResult,
    summary="Soft-delete records deleted in Health Connect",
    responses=_ERRORS,
)
async def ingest_deletions(
    batch: DeletionsBatch, token: IngestAuth, session: Db, settings: SettingsDep
) -> DeletionsResult:
    _check_size(len(batch.items), settings)
    result = await svc.ingest_deletions(session, settings, token.id, batch)
    await session.commit()
    return result


@router.post(
    "/daily-aggregates",
    response_model=DailyAggregatesResult,
    summary="Store official Health Connect daily aggregates",
    responses=_ERRORS,
)
async def ingest_daily_aggregates(
    batch: DailyAggregatesBatch, token: IngestAuth, session: Db, settings: SettingsDep
) -> DailyAggregatesResult:
    _check_size(len(batch.items), settings)
    result = await svc.ingest_daily_aggregates(session, settings, token.id, batch)
    await session.commit()
    return result


@router.post(
    "/sync-report",
    response_model=SyncReportResult,
    summary="Close a sync run",
    responses=_ERRORS,
)
async def ingest_sync_report(
    report: SyncReport, token: IngestAuth, session: Db
) -> SyncReportResult:
    await svc.ingest_sync_report(session, token.id, report)
    await session.commit()
    return SyncReportResult(sync_id=report.sync_id)

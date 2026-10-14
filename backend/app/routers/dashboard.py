"""Read API for the web dashboard. Cookie-session auth (no ingest token), GET only."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Query

from app.dash_schemas import (
    Agg,
    Bucket,
    InventoryResponse,
    ReconciliationResponse,
    SeriesResponse,
    SeriesSource,
    SyncStatusResponse,
    TodaySummary,
)
from app.deps import AdminAuth, Db, SettingsDep
from app.errors import ApiError
from app.schemas import ErrorResponse
from app.services import queries

router = APIRouter(prefix="/api/v1", tags=["dashboard"])
_AUTH: dict[int | str, dict[str, Any]] = {401: {"model": ErrorResponse}}


@router.get(
    "/summary/today",
    response_model=TodaySummary,
    summary="Snapshot of a local day (default: today, Europe/Rome)",
    responses=_AUTH,
)
async def summary_today(
    _: AdminAuth,
    session: Db,
    settings: SettingsDep,
    day: Annotated[date | None, Query(alias="date")] = None,
) -> TodaySummary:
    return await queries.today_summary(session, settings, day or queries.today_local(settings))


@router.get(
    "/metrics/{type_name}/series",
    response_model=SeriesResponse,
    response_model_by_alias=True,
    summary="Bucketed time series for one record type",
    responses={**_AUTH, 404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
async def metric_series(
    type_name: str,
    _: AdminAuth,
    session: Db,
    settings: SettingsDep,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
    bucket: Bucket = "auto",
    agg: Agg | None = None,
    source: SeriesSource = "auto",
) -> SeriesResponse:
    last = to or queries.today_local(settings)
    first = from_ or last - timedelta(days=6)
    return await queries.metric_series(
        session, settings, type_name, first, last, bucket, agg, source
    )


@router.get(
    "/data/inventory",
    response_model=InventoryResponse,
    summary="What is stored: counts per type and per source, first/last record",
    responses=_AUTH,
)
async def data_inventory(_: AdminAuth, session: Db) -> InventoryResponse:
    return await queries.inventory(session)


@router.get(
    "/data/reconciliation",
    response_model=ReconciliationResponse,
    response_model_by_alias=True,
    summary="Official Health Connect daily totals vs totals computed from raw records",
    responses={**_AUTH, 422: {"model": ErrorResponse}},
)
async def data_reconciliation(
    _: AdminAuth,
    session: Db,
    settings: SettingsDep,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
    types: Annotated[str | None, Query(description="Comma-separated record types")] = None,
) -> ReconciliationResponse:
    last = to or queries.today_local(settings)
    first = from_ or last - timedelta(days=13)
    chosen = [t.strip() for t in types.split(",") if t.strip()] if types else None
    if chosen is not None and not chosen:
        raise ApiError(422, "invalid_types", "No type given")
    return await queries.reconciliation(
        session, settings, first, last, chosen or queries.RECONCILE_DEFAULT_TYPES
    )


@router.get(
    "/sync/status",
    response_model=SyncStatusResponse,
    summary="Devices and recent sync runs (with refused records and Reader errors)",
    responses=_AUTH,
)
async def sync_status(
    _: AdminAuth, session: Db, limit: Annotated[int, Query(ge=1, le=100)] = 20
) -> SyncStatusResponse:
    return await queries.sync_status(session, limit)

"""Read API for the web dashboard. Cookie-session auth (no ingest token), GET only."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query

from app.config import Settings
from app.dash_schemas import (
    Agg,
    Bucket,
    DataBounds,
    DaypartResponse,
    ExerciseResponse,
    ExerciseRules,
    InventoryResponse,
    OverrideBody,
    OverrideResult,
    PointsRules,
    PointsSeriesResponse,
    PointsWeek,
    ReconciliationResponse,
    ReportDailyResponse,
    ReportResponse,
    SeriesResponse,
    SeriesSource,
    SleepNightsResponse,
    StorageResponse,
    SyncStatusResponse,
    TodaySummary,
)
from app.deps import AdminAuth, Db, SettingsDep
from app.errors import ApiError
from app.schemas import ErrorResponse
from app.services import analytics, daypart, points_api, queries, storage, workouts

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
    field: Annotated[str | None, Query(description="BloodPressure: systolic | diastolic")] = None,
    band: Annotated[bool, Query(description="Add min/max per bucket (lo/hi)")] = False,
    compare: Annotated[bool, Query(description="Add the previous period (prev)")] = False,
    ma: Annotated[bool, Query(description="Add a trailing moving average (ma)")] = False,
    per_day: Annotated[
        bool,
        Query(
            description="Week/month buckets hold the mean per day (days with data), not the total"
        ),
    ] = False,
) -> SeriesResponse:
    last = to or queries.today_local(settings)
    first = from_ or last - timedelta(days=6)
    return await queries.metric_series(
        session,
        settings,
        type_name,
        first,
        last,
        bucket,
        agg,
        source,
        field=field,
        band=band,
        compare=compare,
        ma=ma,
        per_day=per_day,
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
    _: AdminAuth,
    session: Db,
    settings: SettingsDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> SyncStatusResponse:
    return await queries.sync_status(session, limit, settings)


def _window(
    settings: Settings, from_: date | None, to: date | None, default_days: int
) -> tuple[date, date]:
    last = to or queries.today_local(settings)
    return from_ or last - timedelta(days=default_days - 1), last


@router.get(
    "/data/bounds",
    response_model=DataBounds,
    summary="First and last day with data (feeds the 'All' range)",
    responses=_AUTH,
)
async def data_bounds(_: AdminAuth, session: Db) -> DataBounds:
    return await analytics.bounds(session)


@router.get(
    "/heart/daypart",
    response_model=DaypartResponse,
    response_model_by_alias=True,
    summary="Heart rate by day part: night = inside sleep sessions (fallback 23:00-07:00)",
    responses={**_AUTH, 422: {"model": ErrorResponse}},
)
async def heart_daypart(
    _: AdminAuth,
    session: Db,
    settings: SettingsDep,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
    bucket: Annotated[Literal["day", "week", "month"], Query()] = "day",
    include_workouts: Annotated[
        bool, Query(description="Keep real workouts (and 30 min after) in the daytime heart rate")
    ] = False,
) -> DaypartResponse:
    first, last = _window(settings, from_, to, 7)
    return await daypart.daypart(session, settings, first, last, bucket, include_workouts)


@router.get(
    "/storage",
    response_model=StorageResponse,
    summary="Space used by the data, per-table sizes, growth estimate, disk, limits and retention",
    responses=_AUTH,
)
async def storage_info(_: AdminAuth, session: Db, settings: SettingsDep) -> dict[str, Any]:
    return await storage.storage_report(session, settings)


@router.get(
    "/heart/points",
    response_model=PointsSeriesResponse,
    response_model_by_alias=True,
    summary="Heart Points per day / week / month / year (sum of the daily points)",
    responses={**_AUTH, 422: {"model": ErrorResponse}},
)
async def heart_points(
    _: AdminAuth,
    session: Db,
    settings: SettingsDep,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
    bucket: Annotated[Literal["day", "week", "month", "year"], Query()] = "week",
) -> dict[str, Any]:
    first, last = _window(settings, from_, to, 84)
    return await points_api.points_series(session, settings, first, last, bucket)


@router.get(
    "/heart/points/week",
    response_model=PointsWeek,
    summary="The Monday-Sunday week that contains `date` (default today): points vs the goal",
    responses=_AUTH,
)
async def heart_points_week(
    _: AdminAuth,
    session: Db,
    settings: SettingsDep,
    day: Annotated[date | None, Query(alias="date")] = None,
) -> dict[str, Any]:
    return await points_api.points_week(session, settings, day or queries.today_local(settings))


@router.get(
    "/heart/points/rules",
    response_model=PointsRules,
    summary="The Heart Points rules, from the constants the calculation uses",
    responses=_AUTH,
)
async def heart_points_rules(_: AdminAuth, settings: SettingsDep) -> dict[str, Any]:
    return points_api.describe_points_rules(settings)


@router.get(
    "/sleep/nights",
    response_model=SleepNightsResponse,
    response_model_by_alias=True,
    summary="Per-night sleep: duration, stages, bed and wake time, regularity",
    responses={**_AUTH, 422: {"model": ErrorResponse}},
)
async def sleep_nights(
    _: AdminAuth,
    session: Db,
    settings: SettingsDep,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
) -> SleepNightsResponse:
    first, last = _window(settings, from_, to, 30)
    return await analytics.sleep_nights(session, settings, first, last)


@router.get(
    "/exercise/sessions",
    response_model=ExerciseResponse,
    response_model_by_alias=True,
    summary="Workouts (de-duplicated across apps) with kcal, average HR and weekly volume",
    responses={**_AUTH, 422: {"model": ErrorResponse}},
)
async def exercise_sessions(
    _: AdminAuth,
    session: Db,
    settings: SettingsDep,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
    scope: Annotated[
        Literal["all", "real"], Query(description="real = only real workouts (ADR 0006)")
    ] = "all",
) -> ExerciseResponse:
    first, last = _window(settings, from_, to, 30)
    return await analytics.exercise_sessions(session, settings, first, last, scope)


@router.get(
    "/report",
    response_model=ReportResponse,
    response_model_by_alias=True,
    summary="Period report for the 12 dashboard metrics, with previous-period comparison",
    responses={**_AUTH, 422: {"model": ErrorResponse}},
)
async def period_report(
    _: AdminAuth,
    session: Db,
    settings: SettingsDep,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
) -> ReportResponse:
    first, last = _window(settings, from_, to, 7)
    return await analytics.report(session, settings, first, last)


@router.get(
    "/report/daily",
    response_model=ReportDailyResponse,
    response_model_by_alias=True,
    summary="Daily table of the 12 metrics (source of the CSV export)",
    responses={**_AUTH, 422: {"model": ErrorResponse}},
)
async def report_daily(
    _: AdminAuth,
    session: Db,
    settings: SettingsDep,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
) -> ReportDailyResponse:
    first, last = _window(settings, from_, to, 7)
    return await analytics.report_daily(session, settings, first, last)


@router.get(
    "/exercise/rules",
    response_model=ExerciseRules,
    summary="The active rules that decide which sessions are real workouts (from the constants)",
    responses=_AUTH,
)
async def exercise_rules(_: AdminAuth) -> dict[str, Any]:
    return workouts.describe_rules()


@router.put(
    "/exercise/sessions/{session_id}/override",
    response_model=OverrideResult,
    summary="Manual verdict: is this session a real workout? (true / false / null = automatic)",
    responses={**_AUTH, 404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
async def exercise_override(
    session_id: int,
    body: OverrideBody,
    _: AdminAuth,
    session: Db,
    settings: SettingsDep,
) -> OverrideResult:
    found = await workouts.set_override(session, settings, session_id, body.value)
    if found is None:
        raise ApiError(404, "unknown_session", "No such workout")
    return OverrideResult(id=found.workout.id, override=found.override, is_real=found.is_real)

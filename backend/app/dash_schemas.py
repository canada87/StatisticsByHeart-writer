"""Response models of the dashboard read API (session auth; outside the Reader contract)."""

from __future__ import annotations

from datetime import date as Date
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

DailySource = Literal["hc_official", "computed"]


class MetricValue(BaseModel):
    """A daily number with both views kept visible: official = Health Connect aggregate."""

    value: float | None = Field(description="official if present, else computed")
    unit: str | None = None
    date: Date | None = Field(default=None, description="Local day the value belongs to")
    source: DailySource | None = None
    official: float | None = None
    computed: float | None = None


class LatestSample(BaseModel):
    time: datetime
    value: float


class HeartSummary(BaseModel):
    current: LatestSample | None = Field(description="Most recent heart-rate sample ever stored")
    resting: MetricValue
    avg: float | None = None
    min: float | None = None
    max: float | None = None
    samples: int = 0


class SleepSummary(BaseModel):
    date: Date = Field(description="Wake-up day")
    asleep_s: float | None = Field(description="official if present, else computed")
    official_asleep_s: float | None = None
    computed_asleep_s: float | None = None
    in_bed_s: float | None = None
    stages_s: dict[str, float] = {}
    start: datetime | None = None
    end: datetime | None = None
    sessions: int = 0


class ActivityItem(BaseModel):
    id: int
    type: str
    title: str | None = None
    start: datetime
    end: datetime
    duration_s: float
    source_package: str
    has_route: bool = False


class TodaySummary(BaseModel):
    date: Date
    timezone: str
    generated_at: datetime
    steps: MetricValue
    distance_m: MetricValue
    active_kcal: MetricValue
    total_kcal: MetricValue
    heart: HeartSummary
    sleep: SleepSummary | None
    spo2: MetricValue
    hrv: MetricValue
    activities: list[ActivityItem]
    last_sync_at: datetime | None


Bucket = Literal["auto", "15min", "hour", "day", "week", "month"]
Agg = Literal["sum", "avg", "min", "max", "count"]
SeriesSource = Literal["auto", "official", "computed"]


class SeriesPoint(BaseModel):
    t: str = Field(description="Local day (YYYY-MM-DD) or local datetime with offset")
    v: float | None
    n: int | None = Field(default=None, description="Samples/records behind the value, if known")
    lo: float | None = Field(default=None, description="Lowest value inside the bucket (band=true)")
    hi: float | None = Field(default=None, description="Highest value in the bucket (band=true)")
    ma: float | None = Field(default=None, description="Trailing moving average (ma=true)")
    prev: float | None = Field(
        default=None, description="Value at the same position of the previous period (compare=true)"
    )


class SeriesSummary(BaseModel):
    points: int = Field(description="Buckets with a value")
    min: float | None = None
    max: float | None = None
    avg: float | None = None
    total: float | None = None
    first: float | None = None
    last: float | None = None


class SeriesResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: str
    unit: str | None
    bucket: Literal["15min", "hour", "day", "week", "month"]
    agg: Agg
    from_: Date = Field(alias="from")
    to: Date
    timezone: str
    source: SeriesSource
    source_counts: dict[str, int] = Field(
        description="Days served by hc_official / computed (day-level buckets only)"
    )
    field: str | None = Field(default=None, description="BloodPressure: systolic | diastolic")
    coarsened: bool = Field(
        default=False, description="Bucket made coarser than requested to stay under ~1000 points"
    )
    ma_window: int | None = Field(default=None, description="Buckets in the moving-average window")
    previous_from: Date | None = None
    previous_to: Date | None = None
    previous_summary: SeriesSummary | None = None
    points: list[SeriesPoint]
    summary: SeriesSummary


class SourceInventory(BaseModel):
    package: str
    records: int
    first: datetime | None
    last: datetime | None


class TypeInventory(BaseModel):
    type: str
    unit: str | None
    shape: str
    records: int
    deleted: int
    samples: int
    first: datetime | None
    last: datetime | None
    official_days: int
    computed_days: int
    sources: list[SourceInventory]


class SourceTotals(BaseModel):
    package: str
    records: int
    types: list[str]
    first: datetime | None
    last: datetime | None


class InventoryResponse(BaseModel):
    generated_at: datetime
    records: int
    deleted: int
    samples: int
    types: list[TypeInventory]
    sources: list[SourceTotals]


class SourceBreakdown(BaseModel):
    package: str
    records: int
    raw: float = Field(description="Sum of this source's records, ignoring all others")
    counted: float | None = Field(
        default=None, description="Share kept after de-duplication (cumulative types only)"
    )


class ReconciliationRow(BaseModel):
    date: Date
    type: str
    unit: str | None
    official: float | None
    computed: float | None
    naive: float | None = Field(description="Blind sum of every source: what double counting gives")
    diff: float | None = Field(description="computed - official")
    diff_pct: float | None
    status: Literal["match", "diff", "no_official", "no_computed", "no_data"]
    naive_exceeds_official: bool = Field(
        description="True when summing all sources would overshoot the official value by >5%"
    )
    sources: list[SourceBreakdown]


class ReconciliationSummary(BaseModel):
    rows: int
    matches: int
    diffs: int
    no_official: int
    overlap_rows: int


class ReconciliationResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: Date = Field(alias="from")
    to: Date
    types: list[str]
    rows: list[ReconciliationRow]
    summary: ReconciliationSummary


class RejectionTally(BaseModel):
    type: str
    reason: str
    count: int
    detail: str | None = None


class SyncRunRow(BaseModel):
    sync_id: str
    device_id: str
    device_name: str | None
    mode: str | None
    status: str
    started_at: datetime
    finished_at: datetime | None
    duration_s: float | None
    last_activity_at: datetime
    received: int
    inserted: int
    updated: int
    unchanged: int
    rejected: int
    deletions: int
    aggregates: int
    reported_counts: dict[str, Any] | None
    rejections: list[RejectionTally]
    errors: list[dict[str, Any]]


class DeviceRow(BaseModel):
    id: str
    name: str | None
    model: str | None
    app_version: str | None
    first_seen_at: datetime
    last_seen_at: datetime


class SyncStatusResponse(BaseModel):
    generated_at: datetime
    last_success_at: datetime | None
    last_activity_at: datetime | None
    devices: list[DeviceRow]
    runs: list[SyncRunRow]


# ------------------------------------------------------------------ bounds, sleep, exercise, report


class DataBounds(BaseModel):
    first: Date | None = Field(description="First local day with any of the dashboard metrics")
    last: Date | None


class SleepNight(BaseModel):
    date: Date = Field(description="Wake-up day")
    asleep_s: float | None
    in_bed_s: float | None
    stages_s: dict[str, float]
    start: datetime | None
    end: datetime | None
    bedtime_min: int | None = Field(description="Minutes after 18:00 local when sleep began")
    wake_min: int | None = Field(description="Minutes after 00:00 local when the night ended")


class SleepStats(BaseModel):
    nights: int
    avg_asleep_s: float | None = None
    avg_in_bed_s: float | None = None
    bedtime_avg_min: float | None = None
    wake_avg_min: float | None = None
    bedtime_sd_min: float | None = Field(default=None, description="Std dev: lower = more regular")
    wake_sd_min: float | None = None


class SleepNightsResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: Date = Field(alias="from")
    to: Date
    nights: list[SleepNight]
    summary: SleepStats
    previous: SleepStats


class ExerciseRow(BaseModel):
    id: int
    type: str
    title: str | None
    start: datetime
    end: datetime
    duration_s: float
    kcal: float | None = Field(description="Active kcal during the session, de-duplicated")
    avg_hr: float | None
    source_package: str
    has_route: bool = Field(description="GPS route present (on this or a duplicate copy)")
    hr_coverage: float | None = Field(
        default=None,
        description="Share (0..1) of the minutes of the session with a HeartRate sample",
    )
    has_hr: bool = Field(default=False, description="hr_coverage reaches the minimum (50%)")
    recording_method: str = "unknown"
    started_by_user: bool = Field(
        default=False, description="recording_method active/manual (on any copy)"
    )
    auto_real: bool = Field(default=False, description="Verdict of the rules alone")
    auto_rule: Literal["type", "duration", "ok"] = Field(
        default="ok",
        description="Rule that decided the automatic verdict: excluded type, too short, or none",
    )
    min_duration_min: int = Field(
        default=15, description="Minimum duration (minutes) below which a session is not real"
    )
    override: bool | None = Field(default=None, description="Manual verdict; null = automatic")
    is_real: bool = Field(default=False, description="override if set, else auto_real")


class ExerciseWeek(BaseModel):
    week_start: Date
    count: int
    duration_s: float
    kcal: float


class ExerciseStats(BaseModel):
    count: int
    duration_s: float
    avg_duration_s: float | None = None
    kcal: float | None = None
    by_type: dict[str, int] = {}


class ExerciseResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: Date = Field(alias="from")
    to: Date
    scope: Literal["all", "real"] = Field(
        default="all", description="Which sessions sessions/weekly/summary describe"
    )
    total_count: int = Field(default=0, description="Distinct workouts in the range")
    real_count: int = Field(default=0, description="...of which real workouts")
    sessions: list[ExerciseRow]
    weekly: list[ExerciseWeek]
    summary: ExerciseStats
    previous: ExerciseStats


class DayValue(BaseModel):
    date: Date
    value: float


class PeriodStats(BaseModel):
    days: int
    total: float | None = None
    avg: float | None = None
    min: float | None = None
    max: float | None = None


class ReportMetric(BaseModel):
    key: str
    type: str
    unit: str | None
    kind: Literal["sum", "avg", "range"]
    days_with_data: int
    current: PeriodStats
    previous: PeriodStats
    delta_abs: float | None = Field(description="current - previous, on total (sum) or avg")
    delta_pct: float | None
    higher_is_better: bool | None = Field(description="None: no judgement (weight, HR)")
    best_day: DayValue | None = None
    worst_day: DayValue | None = None
    first: float | None = None
    last: float | None = None
    spark: list[float | None]
    spark_bucket: Literal["day", "week", "month"]
    diastolic: PeriodStats | None = None
    sessions: int | None = Field(default=None, description="Workouts only: number of sessions")


class ReportWorkouts(BaseModel):
    count: int
    duration_s: float
    avg_duration_s: float | None
    per_week: float | None
    by_type: dict[str, int]
    scope: Literal["real"] = Field(default="real", description="Only real workouts are counted")
    excluded: int = Field(default=0, description="Sessions left out because they are not real")


class ReportResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: Date = Field(alias="from")
    to: Date
    days: int
    previous_from: Date
    previous_to: Date
    generated_at: datetime
    timezone: str
    metrics: list[ReportMetric]
    sleep_regularity: SleepStats | None
    workouts: ReportWorkouts


class ReportColumn(BaseModel):
    key: str
    label: str
    unit: str | None


class ReportDailyRow(BaseModel):
    date: Date
    values: dict[str, float | None]


class ReportDailyResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: Date = Field(alias="from")
    to: Date
    columns: list[ReportColumn]
    rows: list[ReportDailyRow]


class NightInterval(BaseModel):
    date: Date = Field(description="Wake-up day the night belongs to (rule of PROJECT_GUIDE 5.2.3)")
    start: datetime
    end: datetime
    source: Literal["sleep", "fixed"] = Field(
        description="sleep = recorded SleepSession(s); fixed = fallback window 23:00-07:00 local"
    )


class WorkoutInterval(BaseModel):
    start: datetime
    end: datetime = Field(description="End of the session")
    recovery_end: datetime = Field(description="End + 30 minutes: samples up to here are excluded")


class DaypartPoint(BaseModel):
    t: str = Field(description="Bucket start (local day, Monday of the week, or first of month)")
    day: float | None = Field(description="Mean heart rate outside the nights (bpm)")
    night: float | None = Field(description="Mean heart rate inside the nights (bpm)")
    day_n: int = Field(description="Samples behind `day`")
    night_n: int = Field(description="Samples behind `night`")


class DaypartStats(BaseModel):
    avg: float | None = Field(description="Mean of the daily means (same rule as the report KPIs)")
    days: int = Field(description="Days with a value")
    samples: int


class DaypartSummary(BaseModel):
    day: DaypartStats
    night: DaypartStats


class DaypartResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: Date = Field(alias="from")
    to: Date
    bucket: Literal["day", "week", "month"]
    timezone: str
    fixed_window: str = Field(description="Fallback night when a day has no sleep session")
    nights: list[NightInterval]
    include_workouts: bool = Field(
        default=False, description="False: daytime excludes real workouts and 30 minutes after"
    )
    workouts: list[WorkoutInterval] = Field(
        default=[], description="Real workouts (with recovery) overlapping the range"
    )
    points: list[DaypartPoint]
    summary: DaypartSummary
    previous_from: Date
    previous_to: Date
    previous_summary: DaypartSummary


class OverrideBody(BaseModel):
    value: bool | None = Field(description="true / false = manual verdict, null = automatic")


class OverrideResult(BaseModel):
    id: int
    override: bool | None
    is_real: bool


class RuleItem(BaseModel):
    id: Literal["override", "type", "duration", "default"]
    params: dict[str, Any] = Field(description="Values of the rule: types, min_minutes...")


class DaytimeHrRule(BaseModel):
    excludes: Literal["real_workouts"]
    recovery_minutes: int


class SignalsInfo(BaseModel):
    hr_min_share: float
    user_started_methods: list[str]
    informative_only: bool


class ExerciseRules(BaseModel):
    rules: list[RuleItem] = Field(description="Classification rules in evaluation order")
    daytime_hr: DaytimeHrRule
    signals: SignalsInfo


class TableStorage(BaseModel):
    name: str
    total_bytes: int = Field(description="Table + indexes + TOAST (pg_total_relation_size)")
    data_bytes: int = Field(description="Total minus indexes")
    index_bytes: int
    rows: int
    rows_exact: bool = Field(description="False: planner/statistics estimate, true: count(*)")


class GrowthEstimate(BaseModel):
    window_days: int = Field(description="Days measured: up to 30, fewer if the data is younger")
    records: int = Field(description="Records ingested in the window (by ingested_at)")
    samples: int = Field(description="Series samples carried by those records")
    bytes: int = Field(description="Estimated size of what was ingested")
    bytes_per_year: int = Field(description="Projection to one year at the same pace")
    estimated: bool = Field(description="Always true: bytes = rows x average row size")


class DiskInfo(BaseModel):
    total_bytes: int
    used_bytes: int
    free_bytes: int
    free_percent: float = Field(
        description="Of the filesystem the API sees (Docker disk of the VM)"
    )


class LimitItem(BaseModel):
    id: Literal[
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
    params: dict[str, Any] = Field(description="The real values of the constant/setting")


class LimitsInfo(BaseModel):
    items: list[LimitItem] = Field(description="Retention and limits, in display order")


class StorageResponse(BaseModel):
    database_bytes: int
    postgres_version: str
    tables: list[TableStorage]
    records_live: int
    records_deleted: int = Field(description="Soft-deleted records (their samples are removed)")
    first_data: datetime | None
    last_data: datetime | None
    last_ingest: datetime | None
    growth: GrowthEstimate
    disk: DiskInfo
    limits: LimitsInfo

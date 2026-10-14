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

"""Read-side queries for the dashboard. Read-only; never logs values."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Float, and_, cast, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.dash_schemas import (
    ActivityItem,
    DeviceRow,
    HeartSummary,
    InventoryResponse,
    LatestSample,
    MetricValue,
    ReconciliationResponse,
    ReconciliationRow,
    ReconciliationSummary,
    RejectionTally,
    SeriesPoint,
    SeriesResponse,
    SeriesSummary,
    SleepSummary,
    SourceBreakdown,
    SourceInventory,
    SourceTotals,
    SyncRunRow,
    SyncStatusResponse,
    TodaySummary,
    TypeInventory,
)
from app.errors import ApiError
from app.health_types import SPECS, DailyKind, TypeSpec
from app.models import DailyMetric, Device, HealthRecord, HealthSample, SyncRun
from app.services.daily import Coverage, Row, counted_values, rank_sources

MAX_SERIES_DAYS = 3660
INTRADAY_MAX_DAYS = {"15min": 3, "hour": 31}
LATEST_LOOKBACK_DAYS = 14
RECONCILE_MAX_DAYS = 120
RECONCILE_DEFAULT_TYPES = [
    "Steps",
    "Distance",
    "ActiveCaloriesBurned",
    "TotalCaloriesBurned",
    "SleepSession",
]
OVERLAP_TOLERANCE = 0.05


def unit_of(spec: TypeSpec) -> str | None:
    return "s" if spec.daily in (DailyKind.SLEEP, DailyKind.SESSION) else spec.unit


def local_bounds(first: date, last: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """UTC instants of [local midnight of first, local midnight after last)."""
    start = datetime.combine(first, time.min, tzinfo=tz).astimezone(UTC)
    end = datetime.combine(last + timedelta(days=1), time.min, tzinfo=tz).astimezone(UTC)
    return start, end


def today_local(settings: Settings) -> date:
    return datetime.now(settings.tz).date()


# --------------------------------------------------------------------------- summary/today


async def _daily(
    session: AsyncSession, types: Sequence[str], first: date, last: date
) -> dict[tuple[str, date, str], DailyMetric]:
    rows = (
        await session.execute(
            select(DailyMetric).where(
                DailyMetric.type.in_(types), DailyMetric.local_date.between(first, last)
            )
        )
    ).scalars()
    return {(r.type, r.local_date, r.source): r for r in rows}


def _metric_value(
    daily: dict[tuple[str, date, str], DailyMetric],
    type_: str,
    day: date,
    field: str,
    unit: str | None,
) -> MetricValue:
    off = daily.get((type_, day, "hc_official"))
    com = daily.get((type_, day, "computed"))
    official = getattr(off, field) if off else None
    computed = getattr(com, field) if com else None
    value = official if official is not None else computed
    source = (
        "hc_official" if official is not None else ("computed" if computed is not None else None)
    )
    return MetricValue(
        value=value,
        unit=unit,
        date=day if value is not None else None,
        source=source,
        official=official,
        computed=computed,
    )


async def _latest_instant(
    session: AsyncSession, type_: str, day: date, unit: str | None
) -> MetricValue:
    """Most recent daily average within the lookback window (official preferred per day)."""
    rows = (
        await session.execute(
            select(DailyMetric)
            .where(
                DailyMetric.type == type_,
                DailyMetric.local_date.between(day - timedelta(days=LATEST_LOOKBACK_DAYS), day),
                DailyMetric.avg_value.is_not(None),
            )
            .order_by(DailyMetric.local_date.desc())
        )
    ).scalars()
    by_day: dict[date, dict[str, DailyMetric]] = defaultdict(dict)
    for r in rows:
        by_day[r.local_date][r.source] = r
    if not by_day:
        return MetricValue(value=None, unit=unit)
    latest = max(by_day)
    return _metric_value(
        {(type_, latest, s): r for s, r in by_day[latest].items()}, type_, latest, "avg_value", unit
    )


async def _sleep_summary(session: AsyncSession, day: date) -> SleepSummary | None:
    rows = (
        await session.execute(
            select(DailyMetric)
            .where(
                DailyMetric.type == "SleepSession",
                DailyMetric.local_date.between(day - timedelta(days=2), day),
            )
            .order_by(DailyMetric.local_date.desc())
        )
    ).scalars()
    by_day: dict[date, dict[str, DailyMetric]] = defaultdict(dict)
    for r in rows:
        by_day[r.local_date][r.source] = r
    if not by_day:
        return None
    latest = max(by_day)
    com, off = by_day[latest].get("computed"), by_day[latest].get("hc_official")
    detail: dict[str, Any] = (com.detail if com and com.detail else {}) or {}
    official = off.sum_value if off else None
    computed = com.sum_value if com else None
    return SleepSummary(
        date=latest,
        asleep_s=official if official is not None else computed,
        official_asleep_s=official,
        computed_asleep_s=computed,
        in_bed_s=detail.get("in_bed_s"),
        stages_s=detail.get("stages_s", {}),
        start=detail.get("first_start"),
        end=detail.get("last_end"),
        sessions=(com.count or 0) if com else 0,
    )


def dedupe_exercise(rows: Sequence[HealthRecord], settings: Settings) -> list[HealthRecord]:
    """A workout logged by two apps appears once: best-ranked copy wins (tie: has a route)."""
    counts: dict[str, float] = defaultdict(float)
    for r in rows:
        counts[r.source_package] += 1
    ranks = rank_sources(counts, settings.source_priority_list)
    coverage = Coverage()
    kept: list[HealthRecord] = []
    for r in sorted(rows, key=lambda r: (ranks[r.source_package], "route" not in r.data)):
        s, e = r.start_ts.timestamp(), (r.end_ts or r.start_ts).timestamp()
        if e > s and coverage.overlap(s, e) / (e - s) > 0.5:
            continue
        kept.append(r)
        coverage.add_all([(s, e)])
    kept.sort(key=lambda r: r.start_ts, reverse=True)
    return kept


def activity_item(r: HealthRecord) -> ActivityItem:
    return ActivityItem(
        id=r.id,
        type=str(r.data.get("exercise_type", "UNKNOWN")),
        title=r.data.get("title"),
        start=r.start_ts,
        end=r.end_ts or r.start_ts,
        duration_s=((r.end_ts or r.start_ts) - r.start_ts).total_seconds(),
        source_package=r.source_package,
        has_route=bool(r.data.get("route")),
    )


async def recent_activities(
    session: AsyncSession, settings: Settings, limit: int = 5
) -> list[ActivityItem]:
    rows = (
        (
            await session.execute(
                select(HealthRecord)
                .where(HealthRecord.type == "ExerciseSession", HealthRecord.deleted_at.is_(None))
                .order_by(HealthRecord.start_ts.desc())
                .limit(limit * 6)
            )
        )
        .scalars()
        .all()
    )
    return [activity_item(r) for r in dedupe_exercise(rows, settings)[:limit]]


async def today_summary(session: AsyncSession, settings: Settings, day: date) -> TodaySummary:
    cumulative = ["Steps", "Distance", "ActiveCaloriesBurned", "TotalCaloriesBurned"]
    daily = await _daily(session, [*cumulative, "HeartRate"], day, day)
    hr_today = daily.get(("HeartRate", day, "computed"))
    latest = (
        await session.execute(
            select(HealthSample.ts, HealthSample.value)
            .where(HealthSample.type == "HeartRate")
            .order_by(HealthSample.ts.desc())
            .limit(1)
        )
    ).first()
    last_sync = (
        await session.execute(
            select(func.max(SyncRun.finished_at)).where(
                SyncRun.status.in_(("completed", "partial"))
            )
        )
    ).scalar()
    return TodaySummary(
        date=day,
        timezone=settings.local_timezone,
        generated_at=datetime.now(UTC),
        steps=_metric_value(daily, "Steps", day, "sum_value", "count"),
        distance_m=_metric_value(daily, "Distance", day, "sum_value", "m"),
        active_kcal=_metric_value(daily, "ActiveCaloriesBurned", day, "sum_value", "kcal"),
        total_kcal=_metric_value(daily, "TotalCaloriesBurned", day, "sum_value", "kcal"),
        heart=HeartSummary(
            current=LatestSample(time=latest[0], value=latest[1]) if latest else None,
            resting=await _latest_instant(session, "RestingHeartRate", day, "bpm"),
            avg=hr_today.avg_value if hr_today else None,
            min=hr_today.min_value if hr_today else None,
            max=hr_today.max_value if hr_today else None,
            samples=(hr_today.count or 0) if hr_today else 0,
        ),
        sleep=await _sleep_summary(session, day),
        spo2=await _latest_instant(session, "OxygenSaturation", day, "percent"),
        hrv=await _latest_instant(session, "HeartRateVariabilityRmssd", day, "ms"),
        activities=await recent_activities(session, settings),
        last_sync_at=last_sync,
    )


# --------------------------------------------------------------------------- series


def _span_days(first: date, last: date) -> int:
    return (last - first).days + 1


def supports_intraday(spec: TypeSpec) -> bool:
    return spec.daily in (DailyKind.SAMPLES, DailyKind.SUM, DailyKind.INSTANT)


def choose_bucket(spec: TypeSpec, first: date, last: date) -> str:
    span = _span_days(first, last)
    if span <= 2 and supports_intraday(spec):
        return "15min"
    if span <= 14 and supports_intraday(spec):
        return "hour"
    if span <= 120:
        return "day"
    return "week" if span <= 800 else "month"


def default_agg(spec: TypeSpec) -> str:
    return "sum" if spec.daily in (DailyKind.SUM, DailyKind.SLEEP, DailyKind.SESSION) else "avg"


def _check_agg(spec: TypeSpec, agg: str) -> None:
    if agg == "sum" and spec.daily in (DailyKind.SAMPLES, DailyKind.INSTANT):
        raise ApiError(
            422, "agg_not_supported", f"{spec.name} has no meaningful sum: use avg/min/max"
        )


def _day_field(row: DailyMetric, agg: str, field: str | None = None) -> float | None:
    if field and field != "systolic":
        # secondary value of a two-value type (BloodPressure diastolic): its stats live in detail
        extra = (row.detail or {}).get(field)
        if not isinstance(extra, dict):
            return None
        if agg == "count":
            return float(row.count) if row.count is not None else None
        value = extra.get(agg if agg in ("avg", "min", "max") else "avg")
        return float(value) if value is not None else None
    if agg == "sum":
        return row.sum_value
    if agg == "count":
        return float(row.count) if row.count is not None else None
    if agg == "avg":
        return row.avg_value if row.avg_value is not None else row.sum_value
    if agg == "min":
        return row.min_value if row.min_value is not None else row.sum_value
    return row.max_value if row.max_value is not None else row.sum_value


def bucket_start(day: date, bucket: str) -> date:
    if bucket == "week":
        return day - timedelta(days=day.weekday())
    if bucket == "month":
        return day.replace(day=1)
    return day


def _next_bucket(start: date, bucket: str) -> date:
    if bucket == "week":
        return start + timedelta(days=7)
    if bucket == "month":
        return (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return start + timedelta(days=1)


def _combine(
    values: list[tuple[float, int | None]], agg: str, plain: bool = False
) -> tuple[float | None, int | None]:
    """One value per bucket from the daily ones.

    ``plain`` = the mean of the daily values (days with data), whatever the daily aggregation: the
    "average per day" of a month, which a partial month does not distort the way a total does.
    """
    if not values:
        return None, None
    n_total = sum(n for _, n in values if n) or None
    if plain and agg in ("sum", "avg"):
        return sum(v for v, _ in values) / len(values), n_total
    if agg in ("sum", "count"):
        return sum(v for v, _ in values), n_total
    if agg == "min":
        return min(v for v, _ in values), n_total
    if agg == "max":
        return max(v for v, _ in values), n_total
    if all(n for _, n in values):
        weight = sum(n or 0 for _, n in values)
        return sum(v * (n or 0) for v, n in values) / weight, n_total
    return sum(v for v, _ in values) / len(values), n_total


def summarize(points: list[SeriesPoint]) -> SeriesSummary:
    vals = [p.v for p in points if p.v is not None]
    if not vals:
        return SeriesSummary(points=0)
    return SeriesSummary(
        points=len(vals),
        min=min(vals),
        max=max(vals),
        avg=sum(vals) / len(vals),
        total=sum(vals),
        first=vals[0],
        last=vals[-1],
    )


async def _day_series(
    session: AsyncSession,
    spec: TypeSpec,
    first: date,
    last: date,
    bucket: str,
    agg: str,
    source: str,
    field: str | None = None,
    plain_mean: bool = False,
) -> tuple[list[SeriesPoint], dict[str, int]]:
    rows = (
        await session.execute(
            select(DailyMetric).where(
                DailyMetric.type == spec.name, DailyMetric.local_date.between(first, last)
            )
        )
    ).scalars()
    per_day: dict[date, dict[str, DailyMetric]] = defaultdict(dict)
    for r in rows:
        per_day[r.local_date][r.source] = r
    order = {
        "auto": ("hc_official", "computed"),
        "official": ("hc_official",),
        "computed": ("computed",),
    }[source]
    served = {"hc_official": 0, "computed": 0}
    by_bucket: dict[date, list[tuple[float, int | None]]] = defaultdict(list)
    lows: dict[date, list[float]] = defaultdict(list)
    highs: dict[date, list[float]] = defaultdict(list)
    ranged = spec.daily in (DailyKind.SAMPLES, DailyKind.INSTANT)  # min/max are real extremes
    for day, sources in per_day.items():
        for src in order:
            row = sources.get(src)
            value = _day_field(row, agg, field) if row else None
            if value is None or row is None:
                continue
            key = bucket_start(day, bucket)
            by_bucket[key].append((value, row.count))
            served[src] += 1
            if ranged:
                lo, hi = _day_field(row, "min", field), _day_field(row, "max", field)
                if lo is not None:
                    lows[key].append(lo)
                if hi is not None:
                    highs[key].append(hi)
            break
    points: list[SeriesPoint] = []
    cursor = bucket_start(first, bucket)
    while cursor <= last:
        v, n = _combine(by_bucket.get(cursor, []), agg, plain_mean)
        points.append(
            SeriesPoint(
                t=cursor.isoformat(),
                v=v,
                n=n,
                days=len(by_bucket.get(cursor, [])) or None,
                lo=min(lows[cursor]) if lows.get(cursor) else None,
                hi=max(highs[cursor]) if highs.get(cursor) else None,
            )
        )
        cursor = _next_bucket(cursor, bucket)
    return points, {k: v for k, v in served.items() if v}


def _floor(dt: datetime, bucket: str) -> datetime:
    minute = 0 if bucket == "hour" else (dt.minute // 15) * 15
    return dt.replace(minute=minute, second=0, microsecond=0)


async def _intraday_series(
    session: AsyncSession,
    settings: Settings,
    spec: TypeSpec,
    first: date,
    last: date,
    bucket: str,
    agg: str,
    field: str | None = None,
) -> list[SeriesPoint]:
    if not supports_intraday(spec):
        raise ApiError(
            422, "bucket_not_supported", f"{spec.name} is only available per day or coarser"
        )
    if _span_days(first, last) > INTRADAY_MAX_DAYS[bucket]:
        raise ApiError(
            422,
            "bucket_too_fine",
            f"bucket={bucket} allows at most {INTRADAY_MAX_DAYS[bucket]} days; use coarser",
        )
    tz = settings.tz
    start, end = local_bounds(first, last, tz)

    if spec.daily is DailyKind.SAMPLES:
        sql_agg = {
            "avg": "avg(value)",
            "min": "min(value)",
            "max": "max(value)",
            "count": "count(*)",
        }
        if agg not in sql_agg:
            raise ApiError(422, "agg_not_supported", f"agg={agg} not available for {spec.name}")
        bin_expr = (
            "date_trunc('hour', ts AT TIME ZONE :tz)"
            if bucket == "hour"
            else "date_bin('15 minutes', ts AT TIME ZONE :tz, TIMESTAMP '2000-01-01')"
        )
        stmt = text(
            f"SELECT {bin_expr} AS b, {sql_agg[agg]} AS v, count(*) AS n FROM health_sample "  # noqa: S608
            "WHERE type = :t AND ts >= :s AND ts < :e GROUP BY b ORDER BY b"
        )
        result = await session.execute(
            stmt, {"tz": settings.local_timezone, "t": spec.name, "s": start, "e": end}
        )
        return [
            SeriesPoint(t=b.replace(tzinfo=tz).isoformat(), v=float(v), n=int(n))
            for b, v, n in result.all()
        ]

    rows = (
        await session.execute(
            select(
                HealthRecord.local_date,
                HealthRecord.start_ts,
                HealthRecord.end_ts,
                HealthRecord.source_package,
                HealthRecord.data,
            ).where(
                HealthRecord.type == spec.name,
                HealthRecord.deleted_at.is_(None),
                HealthRecord.start_ts >= start,
                HealthRecord.start_ts < end,
            )
        )
    ).all()
    key = field or spec.value_keys[0]
    buckets: dict[datetime, list[float]] = defaultdict(list)
    if spec.daily is DailyKind.SUM:
        if agg not in ("sum", "count"):
            raise ApiError(422, "agg_not_supported", f"agg={agg} not available at this bucket size")
        per_day: dict[date, list[Row]] = defaultdict(list)
        for ld, s, e, src, data in rows:
            per_day[ld].append(Row(ld, s, e, src, data))
        for day_rows in per_day.values():
            counted, _ = counted_values(day_rows, key, settings.source_priority_list)
            for row, value, fraction in counted:
                if fraction > 0:
                    buckets[_floor(row.start.astimezone(tz), bucket)].append(value)
    else:
        for _ld, s, _e, _src, data in rows:
            if key in data:
                buckets[_floor(s.astimezone(tz), bucket)].append(float(data[key]))
    out: list[SeriesPoint] = []
    for b in sorted(buckets):
        vals = buckets[b]
        v = {
            "sum": sum(vals),
            "count": float(len(vals)),
            "avg": sum(vals) / len(vals),
            "min": min(vals),
            "max": max(vals),
        }[agg]
        out.append(SeriesPoint(t=b.isoformat(), v=v, n=len(vals)))
    return out


COARSER = {"day": "week", "week": "month"}
MA_WINDOW = {"day": 7, "week": 4, "month": 3}
MAX_POINTS = 1000


def _bucket_count(span: int, bucket: str) -> int:
    if bucket == "day":
        return span
    return -(-span // 7) if bucket == "week" else -(-span // 28)


def _moving_average(points: list[SeriesPoint], window: int) -> None:
    for i, p in enumerate(points):
        vals = [q.v for q in points[max(0, i - window + 1) : i + 1] if q.v is not None]
        p.ma = sum(vals) / len(vals) if vals else None


async def _build_points(
    session: AsyncSession,
    settings: Settings,
    spec: TypeSpec,
    first: date,
    last: date,
    bucket: str,
    agg: str,
    source: str,
    field: str | None,
    per_day: bool = False,
) -> tuple[list[SeriesPoint], dict[str, int]]:
    if bucket in ("15min", "hour"):
        pts = await _intraday_series(session, settings, spec, first, last, bucket, agg, field)
        return pts, {}
    return await _day_series(session, spec, first, last, bucket, agg, source, field, per_day)


async def metric_series(
    session: AsyncSession,
    settings: Settings,
    type_: str,
    first: date,
    last: date,
    bucket: str,
    agg: str | None,
    source: str,
    *,
    field: str | None = None,
    band: bool = False,
    compare: bool = False,
    ma: bool = False,
    per_day: bool = False,
) -> SeriesResponse:
    spec = SPECS.get(type_)
    if spec is None:
        raise ApiError(404, "unknown_type", f"Unsupported type {type_}")
    if last < first:
        raise ApiError(422, "invalid_range", "`to` must not precede `from`")
    span = _span_days(first, last)
    if span > MAX_SERIES_DAYS:
        raise ApiError(422, "range_too_long", f"At most {MAX_SERIES_DAYS} days")
    if field is not None and (type_ != "BloodPressure" or field not in ("systolic", "diastolic")):
        raise ApiError(422, "invalid_field", "field applies to BloodPressure: systolic | diastolic")
    chosen_agg = agg or default_agg(spec)
    _check_agg(spec, chosen_agg)
    chosen_bucket = choose_bucket(spec, first, last) if bucket == "auto" else bucket
    coarsened = False
    # Long ranges are aggregated on the server: never send more than ~1000 points.
    while chosen_bucket in COARSER and _bucket_count(span, chosen_bucket) > MAX_POINTS:
        chosen_bucket = COARSER[chosen_bucket]
        coarsened = True

    points, served = await _build_points(
        session, settings, spec, first, last, chosen_bucket, chosen_agg, source, field, per_day
    )
    window: int | None = None
    if ma and chosen_bucket in MA_WINDOW:
        window = MA_WINDOW[chosen_bucket]
        _moving_average(points, window)
    if not band:
        for p in points:
            p.lo = p.hi = None

    prev_first = prev_last = None
    prev_summary = None
    if compare:
        prev_last = first - timedelta(days=1)
        prev_first = prev_last - timedelta(days=span - 1)
        prev_points, _ = await _build_points(
            session,
            settings,
            spec,
            prev_first,
            prev_last,
            chosen_bucket,
            chosen_agg,
            source,
            field,
            per_day,
        )
        prev_summary = summarize(prev_points)
        if chosen_bucket in ("15min", "hour"):
            # intraday buckets are sparse: align by shifting timestamps back one period
            by_t = {q.t: q.v for q in prev_points}
            shift = timedelta(days=span)
            for p in points:
                p.prev = by_t.get((datetime.fromisoformat(p.t) - shift).isoformat())
        else:
            for i, p in enumerate(points):
                p.prev = prev_points[i].v if i < len(prev_points) else None

    return SeriesResponse(
        type=type_,
        unit="count" if chosen_agg == "count" else unit_of(spec),
        bucket=chosen_bucket,
        agg=chosen_agg,
        from_=first,
        to=last,
        timezone=settings.local_timezone,
        per_day=per_day and chosen_bucket in ("week", "month"),
        source=source,
        source_counts=served,
        field=field,
        coarsened=coarsened,
        ma_window=window,
        previous_from=prev_first,
        previous_to=prev_last,
        previous_summary=prev_summary,
        points=points,
        summary=summarize(points),
    )


# --------------------------------------------------------------------------- inventory


async def inventory(session: AsyncSession) -> InventoryResponse:
    per_source = (
        await session.execute(
            select(
                HealthRecord.type,
                HealthRecord.source_package,
                func.count().filter(HealthRecord.deleted_at.is_(None)),
                func.count().filter(HealthRecord.deleted_at.is_not(None)),
                func.min(HealthRecord.start_ts).filter(HealthRecord.deleted_at.is_(None)),
                func.max(func.coalesce(HealthRecord.end_ts, HealthRecord.start_ts)).filter(
                    HealthRecord.deleted_at.is_(None)
                ),
            ).group_by(HealthRecord.type, HealthRecord.source_package)
        )
    ).all()
    samples = dict(
        (
            await session.execute(
                select(HealthSample.type, func.count()).group_by(HealthSample.type)
            )
        ).all()
    )
    days: dict[tuple[str, str], int] = {
        (t, s): n
        for t, s, n in (
            await session.execute(
                select(DailyMetric.type, DailyMetric.source, func.count()).group_by(
                    DailyMetric.type, DailyMetric.source
                )
            )
        ).all()
    }
    by_type: dict[str, list[tuple[str, int, int, datetime | None, datetime | None]]] = defaultdict(
        list
    )
    by_source: dict[str, list[tuple[str, int, datetime | None, datetime | None]]] = defaultdict(
        list
    )
    for type_, pkg, live, dead, lo, hi in per_source:
        by_type[type_].append((pkg, live, dead, lo, hi))
        by_source[pkg].append((type_, live, lo, hi))

    def _lo(values: list[datetime | None]) -> datetime | None:
        present = [v for v in values if v]
        return min(present) if present else None

    def _hi(values: list[datetime | None]) -> datetime | None:
        present = [v for v in values if v]
        return max(present) if present else None

    types: list[TypeInventory] = []
    for type_ in sorted(set(by_type) | set(samples), key=lambda t: (t not in SPECS, t)):
        entries = by_type.get(type_, [])
        spec = SPECS.get(type_)
        types.append(
            TypeInventory(
                type=type_,
                unit=unit_of(spec) if spec else None,
                shape=spec.shape.value if spec else "unknown",
                records=sum(e[1] for e in entries),
                deleted=sum(e[2] for e in entries),
                samples=samples.get(type_, 0),
                first=_lo([e[3] for e in entries]),
                last=_hi([e[4] for e in entries]),
                official_days=days.get((type_, "hc_official"), 0),
                computed_days=days.get((type_, "computed"), 0),
                sources=sorted(
                    (
                        SourceInventory(package=e[0], records=e[1], first=e[3], last=e[4])
                        for e in entries
                        if e[1]
                    ),
                    key=lambda s: -s.records,
                ),
            )
        )
    sources = sorted(
        (
            SourceTotals(
                package=pkg,
                records=sum(e[1] for e in entries),
                types=sorted(e[0] for e in entries if e[1]),
                first=_lo([e[2] for e in entries]),
                last=_hi([e[3] for e in entries]),
            )
            for pkg, entries in by_source.items()
        ),
        key=lambda s: -s.records,
    )
    return InventoryResponse(
        generated_at=datetime.now(UTC),
        records=sum(t.records for t in types),
        deleted=sum(t.deleted for t in types),
        samples=sum(t.samples for t in types),
        types=types,
        sources=[s for s in sources if s.records],
    )


# --------------------------------------------------------------------------- reconciliation


async def reconciliation(
    session: AsyncSession, settings: Settings, first: date, last: date, types: list[str]
) -> ReconciliationResponse:
    if last < first:
        raise ApiError(422, "invalid_range", "`to` must not precede `from`")
    if _span_days(first, last) > RECONCILE_MAX_DAYS:
        raise ApiError(422, "range_too_long", f"At most {RECONCILE_MAX_DAYS} days")
    for t in types:
        spec = SPECS.get(t)
        if spec is None or spec.daily not in (DailyKind.SUM, DailyKind.SLEEP, DailyKind.SESSION):
            raise ApiError(422, "type_not_supported", f"{t} has no comparable daily total")

    daily = await _daily(session, types, first, last)
    raw: dict[tuple[str, date], dict[str, tuple[int, float]]] = defaultdict(dict)
    for t in types:
        spec = SPECS[t]
        if spec.daily is DailyKind.SUM:
            value: Any = func.coalesce(
                cast(HealthRecord.data[spec.value_keys[0]].astext, Float), 0.0
            )
        else:
            value = func.extract("epoch", HealthRecord.end_ts - HealthRecord.start_ts)
        rows = (
            await session.execute(
                select(
                    HealthRecord.local_date,
                    HealthRecord.source_package,
                    func.count(),
                    func.coalesce(func.sum(value), 0.0),
                )
                .where(
                    and_(
                        HealthRecord.type == t,
                        HealthRecord.deleted_at.is_(None),
                        HealthRecord.local_date.between(first, last),
                    )
                )
                .group_by(HealthRecord.local_date, HealthRecord.source_package)
            )
        ).all()
        for ld, pkg, n, total in rows:
            raw[(t, ld)][pkg] = (int(n), float(total))

    out: list[ReconciliationRow] = []
    day = last
    while day >= first:
        for t in types:
            spec = SPECS[t]
            off = daily.get((t, day, "hc_official"))
            com = daily.get((t, day, "computed"))
            official = off.sum_value if off else None
            computed = com.sum_value if com else None
            per_source = raw.get((t, day), {})
            counted_by_source: dict[str, float] = {}
            if com and com.detail and isinstance(com.detail.get("by_source"), dict):
                counted_by_source = {
                    p: v["counted"]
                    for p, v in com.detail["by_source"].items()
                    if isinstance(v, dict) and "counted" in v
                }
            if official is None and computed is None and not per_source:
                continue
            naive = sum(v for _, v in per_source.values()) if per_source else None
            diff = computed - official if official is not None and computed is not None else None
            diff_pct = (
                diff / official * 100 if diff is not None and official not in (None, 0) else None
            )
            if official is None:
                status = "no_official" if computed is not None else "no_data"
            elif computed is None:
                status = "no_computed"
            else:
                tolerance = max(abs(official) * 0.02, 1.0)
                status = "match" if abs(computed - official) <= tolerance else "diff"
            out.append(
                ReconciliationRow(
                    date=day,
                    type=t,
                    unit=unit_of(spec),
                    official=official,
                    computed=computed,
                    naive=naive,
                    diff=diff,
                    diff_pct=diff_pct,
                    status=status,
                    naive_exceeds_official=bool(
                        naive is not None
                        and official
                        and naive > official * (1 + OVERLAP_TOLERANCE)
                    ),
                    sources=sorted(
                        (
                            SourceBreakdown(
                                package=pkg,
                                records=n,
                                raw=total,
                                counted=counted_by_source.get(pkg),
                            )
                            for pkg, (n, total) in per_source.items()
                        ),
                        key=lambda s: -s.raw,
                    ),
                )
            )
        day -= timedelta(days=1)

    return ReconciliationResponse(
        from_=first,
        to=last,
        types=types,
        rows=out,
        summary=ReconciliationSummary(
            rows=len(out),
            matches=sum(r.status == "match" for r in out),
            diffs=sum(r.status == "diff" for r in out),
            no_official=sum(r.status == "no_official" for r in out),
            overlap_rows=sum(r.naive_exceeds_official for r in out),
        ),
    )


# --------------------------------------------------------------------------- sync status


async def sync_status(session: AsyncSession, limit: int) -> SyncStatusResponse:
    devices = (
        (await session.execute(select(Device).order_by(Device.last_seen_at.desc()))).scalars().all()
    )
    names = {d.id: d.name or d.model for d in devices}
    runs = (
        (
            await session.execute(
                select(SyncRun).order_by(SyncRun.last_activity_at.desc()).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    last_success = (
        await session.execute(
            select(func.max(SyncRun.finished_at)).where(
                SyncRun.status.in_(("completed", "partial"))
            )
        )
    ).scalar()
    last_activity = (await session.execute(select(func.max(SyncRun.last_activity_at)))).scalar()

    def tallies(r: SyncRun) -> list[RejectionTally]:
        out = []
        for key, entry in (r.rejections or {}).items():
            type_, _, reason = key.partition("|")
            out.append(
                RejectionTally(
                    type=type_,
                    reason=reason,
                    count=entry.get("count", 0),
                    detail=entry.get("detail"),
                )
            )
        return sorted(out, key=lambda t: -t.count)

    return SyncStatusResponse(
        generated_at=datetime.now(UTC),
        last_success_at=last_success,
        last_activity_at=last_activity,
        devices=[
            DeviceRow(
                id=str(d.id),
                name=d.name,
                model=d.model,
                app_version=d.app_version,
                first_seen_at=d.first_seen_at,
                last_seen_at=d.last_seen_at,
            )
            for d in devices
        ],
        runs=[
            SyncRunRow(
                sync_id=str(r.id),
                device_id=str(r.device_id),
                device_name=names.get(r.device_id),
                mode=r.mode,
                status=r.status,
                started_at=r.started_at,
                finished_at=r.finished_at,
                duration_s=(r.finished_at - r.started_at).total_seconds()
                if r.finished_at
                else None,
                last_activity_at=r.last_activity_at,
                received=r.records_received,
                inserted=r.records_inserted,
                updated=r.records_updated,
                unchanged=r.records_unchanged,
                rejected=r.records_rejected,
                deletions=r.deletions_applied,
                aggregates=r.aggregates_upserted,
                reported_counts=r.reported_counts,
                rejections=tallies(r),
                errors=r.errors or [],
            )
            for r in runs
        ],
    )

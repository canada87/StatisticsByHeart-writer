"""Trend-oriented read models: sleep nights, workouts, period report, daily export table."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from statistics import mean, pstdev
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.dash_schemas import (
    DataBounds,
    DayValue,
    ExerciseResponse,
    ExerciseRow,
    ExerciseStats,
    ExerciseWeek,
    MonthlyColumn,
    MonthRow,
    PeriodStats,
    ReportColumn,
    ReportDailyResponse,
    ReportDailyRow,
    ReportMetric,
    ReportMonthly,
    ReportPoints,
    ReportResponse,
    ReportWorkouts,
    SeriesPoint,
    SleepNight,
    SleepNightsResponse,
    SleepStats,
    WorkoutTypeDetail,
)
from app.errors import ApiError
from app.health_types import SPECS
from app.models import DailyMetric, HealthRecord, HealthSample
from app.services.daily import Row, counted_values
from app.services.queries import (
    MAX_SERIES_DAYS,
    _bucket_count,
    _day_field,
    _day_series,
    _span_days,
    bucket_start,
    unit_of,
)
from app.services.workouts import MIN_DURATION, Classified, Workout, classify

DASHBOARD_TYPES = [
    "Steps",
    "HeartRate",
    "RestingHeartRate",
    "SleepSession",
    "ExerciseSession",
    "ActiveCaloriesBurned",
    "TotalCaloriesBurned",
    "Distance",
    "Weight",
    "OxygenSaturation",
    "HeartRateVariabilityRmssd",
    "BloodPressure",
]
EXERCISE_LIST_LIMIT = 300


def _check_range(first: date, last: date) -> int:
    if last < first:
        raise ApiError(422, "invalid_range", "`to` must not precede `from`")
    span = _span_days(first, last)
    if span > MAX_SERIES_DAYS:
        raise ApiError(422, "range_too_long", f"At most {MAX_SERIES_DAYS} days")
    return span


def previous_range(first: date, last: date) -> tuple[date, date]:
    span = _span_days(first, last)
    prev_last = first - timedelta(days=1)
    return prev_last - timedelta(days=span - 1), prev_last


# --------------------------------------------------------------------------- bounds


async def bounds(session: AsyncSession) -> DataBounds:
    lo, hi = (
        await session.execute(
            select(func.min(DailyMetric.local_date), func.max(DailyMetric.local_date)).where(
                DailyMetric.type.in_(DASHBOARD_TYPES)
            )
        )
    ).one()
    return DataBounds(first=lo, last=hi)


# --------------------------------------------------------------------------- sleep


def _stats(values: list[float]) -> tuple[float | None, float | None]:
    if not values:
        return None, None
    return mean(values), (pstdev(values) if len(values) > 1 else 0.0)


def sleep_stats(nights: list[SleepNight]) -> SleepStats:
    asleep = [n.asleep_s for n in nights if n.asleep_s is not None]
    in_bed = [n.in_bed_s for n in nights if n.in_bed_s is not None]
    bed_avg, bed_sd = _stats([float(n.bedtime_min) for n in nights if n.bedtime_min is not None])
    wake_avg, wake_sd = _stats([float(n.wake_min) for n in nights if n.wake_min is not None])
    return SleepStats(
        nights=len(nights),
        avg_asleep_s=mean(asleep) if asleep else None,
        avg_in_bed_s=mean(in_bed) if in_bed else None,
        bedtime_avg_min=bed_avg,
        wake_avg_min=wake_avg,
        bedtime_sd_min=bed_sd,
        wake_sd_min=wake_sd,
    )


def _clock_minutes(dt: datetime, settings: Settings, origin_hour: int) -> int:
    local = dt.astimezone(settings.tz)
    return (local.hour * 60 + local.minute - origin_hour * 60) % 1440


async def _nights(
    session: AsyncSession, settings: Settings, first: date, last: date
) -> list[SleepNight]:
    rows = (
        await session.execute(
            select(DailyMetric).where(
                DailyMetric.type == "SleepSession", DailyMetric.local_date.between(first, last)
            )
        )
    ).scalars()
    by_day: dict[date, dict[str, DailyMetric]] = defaultdict(dict)
    for r in rows:
        by_day[r.local_date][r.source] = r
    nights: list[SleepNight] = []
    for day in sorted(by_day):
        com, off = by_day[day].get("computed"), by_day[day].get("hc_official")
        detail = (com.detail if com and com.detail else {}) or {}
        official = off.sum_value if off else None
        asleep = official if official is not None else (com.sum_value if com else None)
        start = datetime.fromisoformat(detail["first_start"]) if detail.get("first_start") else None
        end = datetime.fromisoformat(detail["last_end"]) if detail.get("last_end") else None
        nights.append(
            SleepNight(
                date=day,
                asleep_s=asleep,
                in_bed_s=detail.get("in_bed_s"),
                stages_s=detail.get("stages_s", {}),
                start=start,
                end=end,
                bedtime_min=_clock_minutes(start, settings, 18) if start else None,
                wake_min=_clock_minutes(end, settings, 0) if end else None,
            )
        )
    return nights


async def sleep_nights(
    session: AsyncSession, settings: Settings, first: date, last: date
) -> SleepNightsResponse:
    _check_range(first, last)
    pf, pl = previous_range(first, last)
    nights = await _nights(session, settings, first, last)
    prev = await _nights(session, settings, pf, pl)
    return SleepNightsResponse(
        from_=first, to=last, nights=nights, summary=sleep_stats(nights), previous=sleep_stats(prev)
    )


# --------------------------------------------------------------------------- exercise


async def _exercise_records(
    session: AsyncSession,
    settings: Settings,
    first: date,
    last: date,
    scope: str = "all",
) -> list[Classified]:
    """Distinct workouts of the range; scope="real" keeps only the real ones (ADR 0006)."""
    found = await classify(session, settings, first, last)
    return [c for c in found if c.is_real] if scope == "real" else found


def _duration(r: Workout) -> float:
    return r.duration_s


def _exercise_stats(records: list[Classified], kcal: float | None = None) -> ExerciseStats:
    by_type: dict[str, int] = defaultdict(int)
    for c in records:
        by_type[c.workout.exercise_type] += 1
    total = sum(_duration(c.workout) for c in records)
    return ExerciseStats(
        count=len(records),
        duration_s=total,
        avg_duration_s=total / len(records) if records else None,
        kcal=kcal,
        by_type=dict(sorted(by_type.items(), key=lambda kv: -kv[1])),
    )


@dataclass
class _Kcal:
    start: float
    end: float
    value: float


async def _session_kcal(
    session: AsyncSession, settings: Settings, records: Sequence[Workout]
) -> dict[int, float]:
    """Active kcal inside each session window, from de-duplicated records (proportional overlap)."""
    if not records:
        return {}
    lo = min(r.local_date for r in records) - timedelta(days=1)
    hi = max(r.local_date for r in records) + timedelta(days=1)
    rows = (
        await session.execute(
            select(
                HealthRecord.local_date,
                HealthRecord.start_ts,
                HealthRecord.end_ts,
                HealthRecord.source_package,
                HealthRecord.data,
            ).where(
                HealthRecord.type == "ActiveCaloriesBurned",
                HealthRecord.deleted_at.is_(None),
                HealthRecord.local_date.between(lo, hi),
            )
        )
    ).all()
    per_day: dict[date, list[Row]] = defaultdict(list)
    for ld, s, e, src, data in rows:
        per_day[ld].append(Row(ld, s, e, src, data))
    pieces: list[_Kcal] = []
    for day_rows in per_day.values():
        counted, _ = counted_values(day_rows, "value", settings.source_priority_list)
        for row, value, _frac in counted:
            if value > 0 and row.end is not None:
                pieces.append(_Kcal(row.start.timestamp(), row.end.timestamp(), value))
    out: dict[int, float] = {}
    for r in records:
        s0, e0 = r.start_ts.timestamp(), (r.end_ts or r.start_ts).timestamp()
        total = 0.0
        for p in pieces:
            overlap = min(e0, p.end) - max(s0, p.start)
            if overlap > 0 and p.end > p.start:
                total += p.value * overlap / (p.end - p.start)
        out[r.id] = total
    return out


async def _session_hr(session: AsyncSession, records: Sequence[Workout]) -> dict[int, float]:
    if not records:
        return {}
    rows = (
        await session.execute(
            select(HealthRecord.id, func.avg(HealthSample.value))
            .join(
                HealthSample,
                (HealthSample.type == "HeartRate")
                & (HealthSample.ts >= HealthRecord.start_ts)
                & (HealthSample.ts <= HealthRecord.end_ts),
            )
            .where(HealthRecord.id.in_([r.id for r in records]))
            .group_by(HealthRecord.id)
        )
    ).all()
    return {rid: float(avg) for rid, avg in rows}


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


async def exercise_sessions(
    session: AsyncSession, settings: Settings, first: date, last: date, scope: str = "all"
) -> ExerciseResponse:
    _check_range(first, last)
    pf, pl = previous_range(first, last)
    everything = await _exercise_records(session, settings, first, last)
    records = [c for c in everything if c.is_real] if scope == "real" else everything
    prev = await _exercise_records(session, settings, pf, pl, scope)
    shown = records[:EXERCISE_LIST_LIMIT]
    kcal = await _session_kcal(session, settings, [c.workout for c in records])
    hr = await _session_hr(session, [c.workout for c in shown])

    weeks: dict[date, list[float]] = {}
    cursor = _monday(first)
    while cursor <= last:
        weeks[cursor] = [0, 0.0, 0.0]
        cursor += timedelta(days=7)
    for c in records:
        r = c.workout
        w = weeks.setdefault(_monday(r.start_ts.astimezone(settings.tz).date()), [0, 0.0, 0.0])
        w[0] += 1
        w[1] += _duration(r)
        w[2] += kcal.get(r.id, 0.0)

    return ExerciseResponse(
        from_=first,
        to=last,
        scope="real" if scope == "real" else "all",
        total_count=len(everything),
        real_count=sum(1 for c in everything if c.is_real),
        sessions=[
            ExerciseRow(
                id=c.workout.id,
                type=c.workout.exercise_type,
                title=c.workout.title,
                start=c.workout.start_ts,
                end=c.workout.end,
                duration_s=_duration(c.workout),
                kcal=kcal.get(c.workout.id) or None,
                avg_hr=hr.get(c.workout.id),
                source_package=c.workout.source_package,
                has_route=c.has_gps,
                hr_coverage=c.hr_coverage,
                has_hr=c.has_hr,
                recording_method=c.workout.recording_method,
                started_by_user=c.user_started,
                auto_real=c.auto_real,
                auto_rule=c.auto_rule,
                min_duration_min=int(MIN_DURATION.total_seconds() // 60),
                override=c.override,
                is_real=c.is_real,
            )
            for c in shown
        ],
        weekly=[
            ExerciseWeek(week_start=d, count=int(v[0]), duration_s=v[1], kcal=v[2])
            for d, v in sorted(weeks.items())
        ],
        summary=_exercise_stats(records, sum(kcal.values()) if kcal else None),
        previous=_exercise_stats(prev),
    )


def _workout_points(
    real: list[Classified], first: date, last: date, bucket: str
) -> list[SeriesPoint]:
    """Per-bucket total duration (v) and number (n) of real workouts, one point per bucket."""
    totals: dict[date, tuple[float, int]] = {}
    for c in real:
        key = bucket_start(c.workout.local_date, bucket)
        sec, n = totals.get(key, (0.0, 0))
        totals[key] = (sec + c.workout.duration_s, n + 1)
    points: list[SeriesPoint] = []
    cursor = bucket_start(first, bucket)
    while cursor <= last:
        sec_n = totals.get(cursor)
        points.append(
            SeriesPoint(
                t=cursor.isoformat(),
                v=sec_n[0] if sec_n else None,
                n=sec_n[1] if sec_n else None,
            )
        )
        if bucket == "week":
            cursor += timedelta(days=7)
        elif bucket == "month":
            cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        else:
            cursor += timedelta(days=1)
    return points


# --------------------------------------------------------------------------- report


@dataclass(frozen=True)
class MetricDef:
    key: str
    type: str
    agg: str
    kind: Literal["sum", "avg", "range"]
    higher_is_better: bool | None


REPORT_METRICS = [
    MetricDef("steps", "Steps", "sum", "sum", True),
    MetricDef("heart_rate", "HeartRate", "avg", "range", None),
    MetricDef("resting_hr", "RestingHeartRate", "avg", "avg", False),
    MetricDef("sleep", "SleepSession", "sum", "sum", True),
    MetricDef("workouts", "ExerciseSession", "sum", "sum", True),
    MetricDef("active_kcal", "ActiveCaloriesBurned", "sum", "sum", True),
    MetricDef("total_kcal", "TotalCaloriesBurned", "sum", "sum", None),
    MetricDef("distance", "Distance", "sum", "sum", True),
    MetricDef("weight", "Weight", "avg", "avg", None),
    MetricDef("spo2", "OxygenSaturation", "avg", "avg", True),
    MetricDef("hrv", "HeartRateVariabilityRmssd", "avg", "avg", True),
    MetricDef("blood_pressure", "BloodPressure", "avg", "avg", None),
]


def _period(points: list[SeriesPoint], kind: str, ranged: bool = False) -> PeriodStats:
    vals = [p.v for p in points if p.v is not None]
    if not vals:
        return PeriodStats(days=0)
    lo = min([p.lo for p in points if p.lo is not None] or [min(vals)]) if ranged else min(vals)
    hi = max([p.hi for p in points if p.hi is not None] or [max(vals)]) if ranged else max(vals)
    return PeriodStats(
        days=len(vals),
        total=sum(vals) if kind == "sum" else None,
        avg=mean(vals),
        min=lo,
        max=hi,
    )


def _spark_bucket(span: int) -> Literal["day", "week", "month"]:
    if span <= 93:
        return "day"
    return "week" if _bucket_count(span, "day") <= 800 else "month"


def _metric_from_points(
    *,
    key: str,
    type_: str,
    unit: str | None,
    kind: Literal["sum", "avg", "range"],
    cur: list[SeriesPoint],
    prev: list[SeriesPoint],
    spark_pts: list[SeriesPoint],
    spark_bucket: Literal["day", "week", "month"],
    higher_is_better: bool | None,
    diastolic: PeriodStats | None = None,
    sessions: int | None = None,
) -> ReportMetric:
    ranged = kind == "range"
    cur_stats = _period(cur, kind, ranged)
    prev_stats = _period(prev, kind, ranged)
    basis = "total" if kind == "sum" else "avg"
    c, p = getattr(cur_stats, basis), getattr(prev_stats, basis)
    delta = c - p if c is not None and p is not None else None
    pct = delta / p * 100 if delta is not None and p not in (None, 0) else None
    with_val = [(pt.t, pt.v) for pt in cur if pt.v is not None]
    best = worst = None
    if higher_is_better is not None and with_val:
        hi_pt = max(with_val, key=lambda x: x[1])
        lo_pt = min(with_val, key=lambda x: x[1])
        b_, w_ = (hi_pt, lo_pt) if higher_is_better else (lo_pt, hi_pt)
        best = DayValue(date=date.fromisoformat(b_[0]), value=b_[1])
        worst = DayValue(date=date.fromisoformat(w_[0]), value=w_[1])
    return ReportMetric(
        key=key,
        type=type_,
        unit=unit,
        kind=kind,
        days_with_data=cur_stats.days,
        current=cur_stats,
        previous=prev_stats,
        delta_abs=delta,
        delta_pct=pct,
        higher_is_better=higher_is_better,
        best_day=best,
        worst_day=worst,
        first=with_val[0][1] if with_val else None,
        last=with_val[-1][1] if with_val else None,
        spark=[pt.v for pt in spark_pts],
        spark_bucket=spark_bucket,
        diastolic=diastolic,
        sessions=sessions,
    )


def _day_points(first: date, last: date, values: dict[date, float]) -> list[SeriesPoint]:
    """One SeriesPoint per calendar day of the range (v is None where there is no value)."""
    out: list[SeriesPoint] = []
    day = first
    while day <= last:
        out.append(SeriesPoint(t=day.isoformat(), v=values.get(day)))
        day += timedelta(days=1)
    return out


def _rebucket(
    first: date, last: date, values: dict[date, float], bucket: str, how: Literal["sum", "avg"]
) -> list[SeriesPoint]:
    """Daily values grouped into week/month buckets (sum or mean of the days that have a value)."""
    groups: dict[date, list[float]] = defaultdict(list)
    for d, v in values.items():
        groups[bucket_start(d, bucket)].append(v)
    out: list[SeriesPoint] = []
    cursor = bucket_start(first, bucket)
    while cursor <= last:
        vals = groups.get(cursor, [])
        out.append(
            SeriesPoint(
                t=cursor.isoformat(),
                v=(sum(vals) if how == "sum" else sum(vals) / len(vals)) if vals else None,
            )
        )
        if bucket == "week":
            cursor += timedelta(days=7)
        else:
            cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
    return out


def _by_month(values: dict[date, float], how: Literal["sum", "avg"]) -> dict[date, float]:
    groups: dict[date, list[float]] = defaultdict(list)
    for d, v in values.items():
        groups[d.replace(day=1)].append(v)
    return {m: (sum(v) if how == "sum" else sum(v) / len(v)) for m, v in groups.items()}


def _month_starts(first: date, last: date) -> list[date]:
    out: list[date] = []
    cursor = first.replace(day=1)
    while cursor <= last:
        out.append(cursor)
        cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
    return out


# (key, kind, unit): what the month-by-month table holds, in column order
MONTHLY_COLUMNS: list[tuple[str, Literal["avg", "sum"], str | None]] = [
    ("heart_rate", "avg", "bpm"),
    ("hr_day", "avg", "bpm"),
    ("hr_night", "avg", "bpm"),
    ("resting_hr", "avg", "bpm"),
    ("hrv", "avg", "ms"),
    ("spo2", "avg", "percent"),
    ("sleep", "avg", "s"),
    ("weight", "avg", "kg"),
    ("systolic", "avg", "mmHg"),
    ("diastolic", "avg", "mmHg"),
    ("steps", "sum", "count"),
    ("distance", "sum", "m"),
    ("active_kcal", "sum", "kcal"),
    ("total_kcal", "sum", "kcal"),
    ("heart_points", "sum", "points"),
    ("workouts", "sum", "count"),
    ("workouts_s", "sum", "s"),
]


async def report(
    session: AsyncSession, settings: Settings, first: date, last: date
) -> ReportResponse:
    # lazy: daypart / points_api import this module (previous_range) at the top
    from app.services import points_api
    from app.services.daypart import _compute

    span = _check_range(first, last)
    pf, pl = previous_range(first, last)
    spark_bucket = _spark_bucket(span)
    metrics: list[ReportMetric] = []
    monthly: dict[str, dict[date, float]] = {}
    all_now = await _exercise_records(session, settings, first, last)
    real_now = [c for c in all_now if c.is_real]
    real_prev = await _exercise_records(session, settings, pf, pl, "real")
    for m in REPORT_METRICS:
        spec = SPECS[m.type]
        if m.key == "workouts":
            # only real workouts count and add up (ADR 0006)
            cur = _workout_points(real_now, first, last, "day")
            prev = _workout_points(real_prev, pf, pl, "day")
            spark_pts = (
                cur
                if spark_bucket == "day"
                else _workout_points(real_now, first, last, spark_bucket)
            )
        else:
            cur, _ = await _day_series(session, spec, first, last, "day", m.agg, "auto")
            prev, _ = await _day_series(session, spec, pf, pl, "day", m.agg, "auto")
            if spark_bucket == "day":
                spark_pts = cur
            else:
                spark_pts, _ = await _day_series(
                    session, spec, first, last, spark_bucket, m.agg, "auto"
                )
        diastolic = None
        if m.type == "BloodPressure":
            dia, _ = await _day_series(
                session, spec, first, last, "day", "avg", "auto", "diastolic"
            )
            diastolic = _period(dia, "avg")
            monthly["diastolic"] = _by_month(
                {date.fromisoformat(p.t): p.v for p in dia if p.v is not None}, "avg"
            )
        if m.key != "workouts":
            how: Literal["sum", "avg"] = "sum" if m.kind == "sum" else "avg"
            key = "systolic" if m.key == "blood_pressure" else m.key
            monthly[key] = _by_month(
                {date.fromisoformat(p.t): p.v for p in cur if p.v is not None}, how
            )
        metrics.append(
            _metric_from_points(
                key=m.key,
                type_=m.type,
                unit=unit_of(spec),
                kind=m.kind,
                cur=cur,
                prev=prev,
                spark_pts=spark_pts,
                spark_bucket=spark_bucket,
                higher_is_better=m.higher_is_better,
                diastolic=diastolic,
                sessions=sum(pt.n or 0 for pt in cur) if m.key == "workouts" else None,
            )
        )

    # --- day / night heart rate (same definition as /heart/daypart: night = sleep, daytime
    # without real workouts and the 30 minutes after) and Heart Points
    _, days_now, _w = await _compute(session, settings, first, last)
    _, days_prev, _w2 = await _compute(session, settings, pf, pl)

    def _hr_values(per_day: dict[date, Any], night: bool) -> dict[date, float]:
        out: dict[date, float] = {}
        for d, st in per_day.items():
            v = st.night_avg if night else st.daytime(False)[0]
            if v is not None:
                out[d] = v
        return out

    pts_now = await points_api._daily(session, first, last)
    pts_prev = await points_api._daily(session, pf, pl)
    extras: list[
        tuple[
            str, str, str, Literal["sum", "avg"], dict[date, float], dict[date, float], bool | None
        ]
    ] = [
        (
            "hr_day",
            "HeartRateDay",
            "bpm",
            "avg",
            _hr_values(days_now, False),
            _hr_values(days_prev, False),
            None,
        ),
        (
            "hr_night",
            "HeartRateNight",
            "bpm",
            "avg",
            _hr_values(days_now, True),
            _hr_values(days_prev, True),
            None,
        ),
        ("heart_points", "HeartPoints", "points", "sum", pts_now, pts_prev, True),
    ]
    extra_metrics: list[ReportMetric] = []
    for key, type_, unit, how, vals_now, vals_prev, better in extras:
        monthly[key] = _by_month(vals_now, how)
        cur = _day_points(first, last, vals_now)
        spark = (
            cur if spark_bucket == "day" else _rebucket(first, last, vals_now, spark_bucket, how)
        )
        extra_metrics.append(
            _metric_from_points(
                key=key,
                type_=type_,
                unit=unit,
                kind="sum" if how == "sum" else "avg",
                cur=cur,
                prev=_day_points(pf, pl, vals_prev),
                spark_pts=spark,
                spark_bucket=spark_bucket,
                higher_is_better=better,
            )
        )

    # --- workouts: only real ones (ADR 0006): number and time, per month and per type
    wk_count: dict[date, float] = defaultdict(float)
    wk_secs: dict[date, float] = defaultdict(float)
    detail: dict[str, list[float]] = defaultdict(lambda: [0, 0.0])
    for c in real_now:
        month = c.workout.local_date.replace(day=1)
        wk_count[month] += 1
        wk_secs[month] += c.workout.duration_s
        d_ = detail[c.workout.exercise_type]
        d_[0] += 1
        d_[1] += c.workout.duration_s
    monthly["workouts"] = dict(wk_count)
    monthly["workouts_s"] = dict(wk_secs)

    months: list[MonthRow] = []
    for month in _month_starts(first, last):
        month_last = (month.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        lo, hi = max(first, month), min(last, month_last)
        months.append(
            MonthRow(
                month=month,
                days=(hi - lo).days + 1,
                partial=month < first or month_last > last,
                values={key: monthly.get(key, {}).get(month) for key, _k, _u in MONTHLY_COLUMNS},
            )
        )

    week_series = await points_api.points_series(session, settings, first, last, "week")
    total_points = float(week_series["summary"]["total"])
    points = ReportPoints(
        total=total_points,
        previous_total=float(week_series["previous_summary"]["total"]),
        weekly_avg=total_points / (span / 7) if span else None,
        weeks_complete=int(week_series["summary"]["buckets_complete"]),
        weeks_over_goal=int(week_series["summary"]["weeks_over_goal"] or 0),
        goal=int(week_series["weekly_goal"]),
        hr_configured=bool(week_series["hr_configured"]),
    )

    nights = await _nights(session, settings, first, last)
    stats = _exercise_stats(real_now)
    return ReportResponse(
        from_=first,
        to=last,
        days=span,
        previous_from=pf,
        previous_to=pl,
        generated_at=datetime.now(UTC),
        timezone=settings.local_timezone,
        metrics=metrics,
        extra_metrics=extra_metrics,
        sleep_regularity=sleep_stats(nights) if nights else None,
        workouts=ReportWorkouts(
            count=stats.count,
            duration_s=stats.duration_s,
            avg_duration_s=stats.avg_duration_s,
            per_week=stats.count / (span / 7) if span else None,
            by_type=stats.by_type,
            by_type_detail=[
                WorkoutTypeDetail(type=t, count=int(v[0]), duration_s=v[1])
                for t, v in sorted(detail.items(), key=lambda kv: (-kv[1][1], kv[0]))
            ],
            scope="real",
            excluded=len(all_now) - len(real_now),
        ),
        points=points,
        monthly=ReportMonthly(
            columns=[MonthlyColumn(key=k, kind=kind, unit=u) for k, kind, u in MONTHLY_COLUMNS],
            months=months,
        ),
    )


# --------------------------------------------------------------------------- daily export table

DAILY_COLUMNS: list[tuple[str, str, str | None, str, str, str | None]] = [
    # key, label, unit, type, agg, field
    ("steps", "Passi", "count", "Steps", "sum", None),
    ("distance_m", "Distanza", "m", "Distance", "sum", None),
    ("active_kcal", "Calorie attive", "kcal", "ActiveCaloriesBurned", "sum", None),
    ("total_kcal", "Calorie totali", "kcal", "TotalCaloriesBurned", "sum", None),
    ("hr_avg", "FC media", "bpm", "HeartRate", "avg", None),
    ("hr_min", "FC min", "bpm", "HeartRate", "min", None),
    ("hr_max", "FC max", "bpm", "HeartRate", "max", None),
    ("hr_day", "FC diurna", "bpm", "_daypart_day", "avg", None),
    ("hr_night", "FC notturna", "bpm", "_daypart_night", "avg", None),
    ("resting_hr", "FC a riposo", "bpm", "RestingHeartRate", "avg", None),
    ("hrv", "HRV", "ms", "HeartRateVariabilityRmssd", "avg", None),
    ("spo2", "SpO2", "percent", "OxygenSaturation", "avg", None),
    ("sleep_s", "Sonno", "s", "SleepSession", "sum", None),
    ("workouts_n", "Allenamenti", "count", "ExerciseSession", "count", None),
    ("workouts_s", "Durata allenamenti", "s", "ExerciseSession", "sum", None),
    ("weight_kg", "Peso", "kg", "Weight", "avg", None),
    ("bp_systolic", "Pressione sistolica", "mmHg", "BloodPressure", "avg", "systolic"),
    ("bp_diastolic", "Pressione diastolica", "mmHg", "BloodPressure", "avg", "diastolic"),
    ("heart_points", "Punti cardio", "points", "HeartPoints", "sum", None),
]


async def report_daily(
    session: AsyncSession, settings: Settings, first: date, last: date
) -> ReportDailyResponse:
    _check_range(first, last)
    rows = (
        await session.execute(
            select(DailyMetric).where(
                DailyMetric.type.in_([*DASHBOARD_TYPES, "HeartPoints"]),
                DailyMetric.local_date.between(first, last),
            )
        )
    ).scalars()
    by_key: dict[tuple[str, date], dict[str, DailyMetric]] = defaultdict(dict)
    for r in rows:
        by_key[(r.type, r.local_date)][r.source] = r
    real_by_day: dict[date, list[Classified]] = defaultdict(list)
    for c in await _exercise_records(session, settings, first, last, "real"):
        real_by_day[c.workout.local_date].append(c)
    from app.services.daypart import _compute  # lazy: it imports this module

    _, per_day, _w = await _compute(session, settings, first, last)
    out: list[ReportDailyRow] = []
    day = first
    while day <= last:
        values: dict[str, float | None] = {}
        has_any = False
        for key, _label, _unit, type_, agg, field in DAILY_COLUMNS:
            if type_.startswith("_daypart"):
                st = per_day.get(day)
                dv = (
                    None
                    if st is None
                    else (st.daytime(False)[0] if type_.endswith("day") else st.night_avg)
                )
                values[key] = dv
                has_any = has_any or dv is not None
                continue
            sources = by_key.get((type_, day), {})
            value: float | None = None
            # "count" always comes from what the writer computed (official rows carry no sessions)
            order = ("computed",) if agg == "count" else ("hc_official", "computed")
            for src in order:
                row = sources.get(src)
                value = _day_field(row, agg, field) if row else None
                if value is not None:
                    break
            if key in ("workouts_n", "workouts_s"):
                # only real workouts (ADR 0006), not the daily_metric of every logged session
                day_real = real_by_day.get(day, [])
                if not day_real:
                    value = None
                elif key == "workouts_n":
                    value = float(len(day_real))
                else:
                    value = sum(c.workout.duration_s for c in day_real)
            values[key] = value
            has_any = has_any or value is not None
        if has_any:
            out.append(ReportDailyRow(date=day, values=values))
        day += timedelta(days=1)
    return ReportDailyResponse(
        from_=first,
        to=last,
        columns=[ReportColumn(key=k, label=lbl, unit=u) for k, lbl, u, *_ in DAILY_COLUMNS],
        rows=out,
    )

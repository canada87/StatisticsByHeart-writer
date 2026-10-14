"""Recompute ``daily_metric`` rows (source = 'computed') for the (type, local_date) pairs touched.

Rule that matters: Fit, Feelfit and Withings all write into Health Connect, so the same walk can
exist several times. Cumulative values are therefore NEVER summed blindly:

* sources are ranked (configured priority first, then by how much data they hold that day);
* a record from a lower-ranked source only counts for the part of its time span that is not already
  covered by higher-ranked sources (proportional share of its value);
* sessions (sleep, exercise) from a lower-ranked source overlapping >50% with an accepted one are
  dropped as duplicates.

The official Health Connect aggregates (source = 'hc_official') are stored separately and win in
the UI; the computed rows are the detail/fallback view.
"""

from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.health_types import NOT_ASLEEP_STAGES, SPECS, DailyKind, TypeSpec
from app.models import DailyMetric, HealthRecord, HealthSample

SESSION_DUPLICATE_OVERLAP = 0.5


@dataclass
class Row:
    """A stored record reduced to what aggregation needs."""

    local_date: date
    start: datetime
    end: datetime | None
    source: str
    data: dict[str, Any]


@dataclass
class Metric:
    sum: float | None = None
    avg: float | None = None
    min: float | None = None
    max: float | None = None
    count: int | None = None
    detail: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- source ranking


def rank_sources(totals: dict[str, float], priority: list[str]) -> dict[str, int]:
    """Lower rank = more trusted. Configured packages first, the rest by data volume then name."""
    ranks = {p: priority.index(p) for p in totals if p in priority}
    rest = sorted((p for p in totals if p not in ranks), key=lambda p: (-totals[p], p))
    for i, p in enumerate(rest):
        ranks[p] = len(priority) + i
    return ranks


class Coverage:
    """Union of time intervals (seconds since epoch), kept merged and sorted."""

    def __init__(self) -> None:
        self._starts: list[float] = []
        self._ends: list[float] = []

    def add_all(self, intervals: Iterable[tuple[float, float]]) -> None:
        merged: list[tuple[float, float]] = []
        existing = zip(self._starts, self._ends, strict=True)
        for s, e in sorted([*existing, *((s, e) for s, e in intervals if e > s)]):
            if merged and s <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], e))
            else:
                merged.append((s, e))
        self._starts = [s for s, _ in merged]
        self._ends = [e for _, e in merged]

    def overlap(self, s: float, e: float) -> float:
        i = bisect_right(self._ends, s)
        total = 0.0
        while i < len(self._starts) and self._starts[i] < e:
            total += min(e, self._ends[i]) - max(s, self._starts[i])
            i += 1
        return total

    def covers_point(self, t: float) -> bool:
        i = bisect_right(self._ends, t)
        return i < len(self._starts) and self._starts[i] < t


def _span(row: Row) -> tuple[float, float]:
    s = row.start.timestamp()
    return s, (row.end or row.start).timestamp()


def _by_source(rows: list[Row]) -> dict[str, list[Row]]:
    grouped: dict[str, list[Row]] = defaultdict(list)
    for r in rows:
        grouped[r.source].append(r)
    return grouped


# --------------------------------------------------------------------------- per-kind day math


def _num(data: dict[str, Any], key: str) -> float:
    v = data.get(key)
    return float(v) if isinstance(v, int | float) else 0.0


def counted_values(
    rows: list[Row], key: str, priority: list[str]
) -> tuple[list[tuple[Row, float, float]], dict[str, dict[str, float]]]:
    """(row, counted value, counted fraction) per record after de-dup, plus per-source stats."""
    grouped = _by_source(rows)
    totals = {p: sum(_num(r.data, key) for r in rs) for p, rs in grouped.items()}
    ranks = rank_sources(totals, priority)
    coverage = Coverage()
    by_source: dict[str, dict[str, float]] = {}
    counted_rows: list[tuple[Row, float, float]] = []
    for source in sorted(grouped, key=lambda p: ranks[p]):
        counted = 0.0
        for r in grouped[source]:
            s, e = _span(r)
            if e > s:
                fraction = 1.0 - coverage.overlap(s, e) / (e - s)
            else:
                fraction = 0.0 if coverage.covers_point(s) else 1.0
            value = _num(r.data, key) * fraction
            counted += value
            counted_rows.append((r, value, fraction))
        coverage.add_all(_span(r) for r in grouped[source])
        by_source[source] = {
            "records": len(grouped[source]),
            "raw": round(totals[source], 4),
            "counted": round(counted, 4),
        }
    return counted_rows, by_source


def sum_for_day(rows: list[Row], key: str, priority: list[str]) -> Metric:
    counted_rows, by_source = counted_values(rows, key, priority)
    return Metric(
        sum=sum(v for _, v, _f in counted_rows),
        count=sum(1 for _, _v, f in counted_rows if f > 0),
        detail={"method": "priority_interval_subtraction", "by_source": by_source},
    )


def instant_for_day(rows: list[Row], keys: tuple[str, ...], priority: list[str]) -> Metric:
    grouped = _by_source(rows)
    ranks = rank_sources({p: float(len(rs)) for p, rs in grouped.items()}, priority)
    # The same reading mirrored by two apps (same instant) counts once, from the best source.
    kept: dict[datetime, Row] = {}
    for r in sorted(rows, key=lambda r: (ranks[r.source], r.start)):
        kept.setdefault(r.start, r)
    chosen = sorted(kept.values(), key=lambda r: r.start)
    primary = [_num(r.data, keys[0]) for r in chosen if keys[0] in r.data]
    detail: dict[str, Any] = {
        "method": "same_instant_dedupe",
        "by_source": {p: {"records": len(rs)} for p, rs in grouped.items()},
    }
    if chosen:
        last = chosen[-1]
        detail["last"] = {"time": last.start.isoformat(), "value": last.data.get(keys[0])}
    for extra in keys[1:]:
        vals = [_num(r.data, extra) for r in chosen if extra in r.data]
        if vals:
            detail[extra] = {"avg": sum(vals) / len(vals), "min": min(vals), "max": max(vals)}
    if not primary:
        return Metric(count=0, detail=detail)
    return Metric(
        avg=sum(primary) / len(primary),
        min=min(primary),
        max=max(primary),
        count=len(primary),
        detail=detail,
    )


def _dedupe_sessions(rows: list[Row], priority: list[str]) -> tuple[list[Row], dict[str, int]]:
    grouped = _by_source(rows)
    totals = {
        p: sum((_span(r)[1] - _span(r)[0]) for r in rs) or float(len(rs))
        for p, rs in grouped.items()
    }
    ranks = rank_sources(totals, priority)
    coverage = Coverage()
    accepted: list[Row] = []
    for source in sorted(grouped, key=lambda p: ranks[p]):
        for r in grouped[source]:
            s, e = _span(r)
            duration = e - s
            if duration > 0 and coverage.overlap(s, e) / duration > SESSION_DUPLICATE_OVERLAP:
                continue
            accepted.append(r)
        coverage.add_all(_span(r) for r in grouped[source])
    return accepted, ranks


def _session_seconds(row: Row) -> float:
    s, e = _span(row)
    return e - s


def sleep_for_day(rows: list[Row], priority: list[str]) -> Metric:
    accepted, _ = _dedupe_sessions(rows, priority)
    asleep = 0.0
    in_bed = 0.0
    stages_s: dict[str, float] = defaultdict(float)
    by_source: dict[str, int] = defaultdict(int)
    for r in accepted:
        by_source[r.source] += 1
        in_bed += _session_seconds(r)
        stages = r.data.get("stages") or []
        if not stages:
            asleep += _session_seconds(r)
            continue
        for st in stages:
            dur = (
                datetime.fromisoformat(st["end_time"]) - datetime.fromisoformat(st["start_time"])
            ).total_seconds()
            stages_s[st["stage"]] += dur
            if st["stage"] not in NOT_ASLEEP_STAGES:
                asleep += dur
    detail: dict[str, Any] = {
        "method": "session_overlap_dedupe",
        "in_bed_s": in_bed,
        "stages_s": dict(stages_s),
        "by_source": dict(by_source),
    }
    if accepted:
        detail["first_start"] = min(r.start for r in accepted).isoformat()
        detail["last_end"] = max((r.end or r.start) for r in accepted).isoformat()
    return Metric(sum=asleep, count=len(accepted), detail=detail)


def session_for_day(rows: list[Row], priority: list[str]) -> Metric:
    accepted, _ = _dedupe_sessions(rows, priority)
    by_kind: dict[str, int] = defaultdict(int)
    by_source: dict[str, int] = defaultdict(int)
    for r in accepted:
        by_kind[
            str(r.data.get("exercise_type") or r.data.get("mindfulness_type") or "unknown")
        ] += 1
        by_source[r.source] += 1
    return Metric(
        sum=sum(_session_seconds(r) for r in accepted),
        count=len(accepted),
        detail={
            "method": "session_overlap_dedupe",
            "by_kind": dict(by_kind),
            "by_source": dict(by_source),
        },
    )


# --------------------------------------------------------------------------- orchestration


async def _fetch_rows(session: AsyncSession, type_: str, dates: set[date]) -> dict[date, list[Row]]:
    stmt = select(
        HealthRecord.local_date,
        HealthRecord.start_ts,
        HealthRecord.end_ts,
        HealthRecord.source_package,
        HealthRecord.data,
    ).where(
        HealthRecord.type == type_,
        HealthRecord.local_date.in_(dates),
        HealthRecord.deleted_at.is_(None),
    )
    out: dict[date, list[Row]] = defaultdict(list)
    for ld, start, end, source, data in (await session.execute(stmt)).all():
        out[ld].append(Row(ld, start, end, source, data))
    return out


async def _samples_metrics(
    session: AsyncSession, type_: str, dates: set[date]
) -> dict[date, Metric]:
    stmt = (
        select(
            HealthSample.local_date,
            HealthRecord.source_package,
            func.count(),
            func.sum(HealthSample.value),
            func.min(HealthSample.value),
            func.max(HealthSample.value),
        )
        .join(HealthRecord, HealthRecord.id == HealthSample.record_id)
        .where(
            HealthSample.type == type_,
            HealthSample.local_date.in_(dates),
            HealthRecord.deleted_at.is_(None),
        )
        .group_by(HealthSample.local_date, HealthRecord.source_package)
    )
    acc: dict[date, dict[str, tuple[int, float, float, float]]] = defaultdict(dict)
    for ld, source, n, total, lo, hi in (await session.execute(stmt)).all():
        acc[ld][source] = (n, total, lo, hi)
    out: dict[date, Metric] = {}
    for ld, per_source in acc.items():
        n = sum(v[0] for v in per_source.values())
        total = sum(v[1] for v in per_source.values())
        out[ld] = Metric(
            sum=None,
            avg=total / n,
            min=min(v[2] for v in per_source.values()),
            max=max(v[3] for v in per_source.values()),
            count=n,
            detail={
                "method": "all_samples",
                "by_source": {
                    p: {"samples": v[0], "avg": v[1] / v[0]} for p, v in per_source.items()
                },
            },
        )
    return out


async def compute_type(
    session: AsyncSession, spec: TypeSpec, dates: set[date], priority: list[str]
) -> dict[date, Metric]:
    if spec.daily is DailyKind.SAMPLES:
        return await _samples_metrics(session, spec.name, dates)
    rows_by_date = await _fetch_rows(session, spec.name, dates)
    out: dict[date, Metric] = {}
    for ld, rows in rows_by_date.items():
        match spec.daily:
            case DailyKind.SUM:
                out[ld] = sum_for_day(rows, spec.value_keys[0], priority)
            case DailyKind.INSTANT:
                out[ld] = instant_for_day(rows, spec.value_keys, priority)
            case DailyKind.SLEEP:
                out[ld] = sleep_for_day(rows, priority)
            case DailyKind.SESSION:
                out[ld] = session_for_day(rows, priority)
            case _:  # pragma: no cover
                raise AssertionError(spec.daily)
    return out


def _unit(spec: TypeSpec) -> str | None:
    if spec.daily in (DailyKind.SLEEP, DailyKind.SESSION):
        return "s"
    return spec.unit


async def recompute_days(
    session: AsyncSession, keys: Iterable[tuple[str, date]], settings: Settings
) -> int:
    """Recompute the computed daily_metric rows for the given (type, local_date) pairs."""
    by_type: dict[str, set[date]] = defaultdict(set)
    for type_, d in keys:
        by_type[type_].add(d)
    priority = settings.source_priority_list
    written = 0
    for type_, dates in by_type.items():
        spec = SPECS.get(type_)
        if spec is None:
            continue
        metrics = await compute_type(session, spec, dates, priority)
        if metrics:
            rows = [
                {
                    "local_date": ld,
                    "type": type_,
                    "source": "computed",
                    "sum_value": m.sum,
                    "avg_value": m.avg,
                    "min_value": m.min,
                    "max_value": m.max,
                    "count": m.count,
                    "unit": _unit(spec),
                    "detail": m.detail,
                    "snapshot_at": func.now(),
                    "updated_at": func.now(),
                }
                for ld, m in metrics.items()
            ]
            stmt = pg_insert(DailyMetric).values(rows)
            stmt = stmt.on_conflict_do_update(
                index_elements=["local_date", "type", "source"],
                set_={
                    c: stmt.excluded[c]
                    for c in (
                        "sum_value",
                        "avg_value",
                        "min_value",
                        "max_value",
                        "count",
                        "unit",
                        "detail",
                        "snapshot_at",
                        "updated_at",
                    )
                },
            )
            await session.execute(stmt)
            written += len(rows)
        empty = dates - metrics.keys()
        if empty:
            await session.execute(
                delete(DailyMetric).where(
                    DailyMetric.type == type_,
                    DailyMetric.source == "computed",
                    DailyMetric.local_date.in_(empty),
                )
            )
    return written

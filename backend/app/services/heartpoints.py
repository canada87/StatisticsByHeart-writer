"""Heart Points (Google Fit / AHA style): minute by minute, over the WHOLE day (ADR 0008).

A minute is worth 1 or 2 points from its heart rate OR its step cadence, never the sum:

* heart rate (mean of the minute): >= 50% of HRmax -> 1, >= 70% -> 2;
* cadence (steps in the minute):    >= 100 -> 1,       >= 130 -> 2;
* the minute scores the MAXIMUM of the two criteria.

The MET criterion of Google Fit is NOT used (Health Connect has no MET). Every heartbeat and every
step counts: workouts are neither excluded nor singled out here.

HRmax = ``SBH_HR_MAX`` if set, else 220 - age with age = day.year - ``SBH_BIRTH_YEAR`` (the year of
the day computed). With neither, heart-rate points are not computed and only cadence counts.
All the numbers below are the rules shown in the dashboard ("Regole dei Punti cardio").
"""

from __future__ import annotations

import hashlib
import logging
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import DailyMetric, HealthRecord
from app.services.daily import Row, counted_values

log = logging.getLogger("sbh.heartpoints")

# --- the rules: all the numbers in one place -------------------------------------------------
HEART_POINTS_TYPE = "HeartPoints"
"""``daily_metric.type`` of the computed daily total (source = computed, unit = points)."""

HR_MODERATE_PCT = 50
HR_VIGOROUS_PCT = 70
"""Share of HRmax: from 50% a minute is worth 1 point, from 70% it is worth 2."""

CADENCE_MODERATE = 100
CADENCE_VIGOROUS = 130
"""Steps per minute: from 100 a minute is worth 1 point, from 130 it is worth 2."""

MODERATE_POINTS = 1
VIGOROUS_POINTS = 2

HR_CARRY_MAX = timedelta(minutes=5)
"""A minute with no heart-rate sample repeats the last value if that sample is at most this old."""

STEPS_MAX_SPAN = timedelta(minutes=60)
"""Step records longer than this are daily/hourly totals, not cadence: ignored."""

WEEKLY_GOAL = 150
"""Weekly goal in points (AHA: 150 minutes of moderate activity)."""

HR_MAX_RANGE = (100, 250)
AGE_RANGE = (1, 110)
"""Sanity ranges: a value outside them is treated as not configured."""


def hr_max_for(settings: Settings, day: date) -> tuple[int | None, str | None]:
    """(HRmax, where it comes from: "override" | "birth_year") for ``day``, or (None, None)."""
    if settings.hr_max is not None and HR_MAX_RANGE[0] <= settings.hr_max <= HR_MAX_RANGE[1]:
        return settings.hr_max, "override"
    if settings.birth_year is not None:
        age = day.year - settings.birth_year
        if AGE_RANGE[0] <= age <= AGE_RANGE[1]:
            return 220 - age, "birth_year"
    return None, None


def config_signature(settings: Settings) -> str:
    """Identifies the HRmax settings the stored points were computed with (no personal value)."""
    raw = f"{settings.birth_year}|{settings.hr_max}"
    return hashlib.sha1(raw.encode()).hexdigest()[:10]  # noqa: S324 (not a security use)


def hr_points(bpm: float, hr_max: int) -> int:
    """Points of one minute from its mean heart rate (integer arithmetic: exact thresholds)."""
    if bpm * 100 >= HR_VIGOROUS_PCT * hr_max:
        return VIGOROUS_POINTS
    if bpm * 100 >= HR_MODERATE_PCT * hr_max:
        return MODERATE_POINTS
    return 0


def cadence_points(steps_per_minute: float) -> int:
    if steps_per_minute >= CADENCE_VIGOROUS:
        return VIGOROUS_POINTS
    if steps_per_minute >= CADENCE_MODERATE:
        return MODERATE_POINTS
    return 0


def minute_points(hr: int, cadence: int) -> int:
    """The minute is worth the maximum of the two criteria, never their sum."""
    return max(hr, cadence)


def _minute(ts: datetime) -> datetime:
    return ts.astimezone(UTC).replace(second=0, microsecond=0)


def carry_forward(
    per_minute: dict[datetime, float], tz_day: date, settings: Settings
) -> dict[datetime, float]:
    """Mean HR per minute, with the last value repeated for up to HR_CARRY_MAX after a sample."""
    out: dict[datetime, float] = {}
    ordered = sorted(per_minute.items())
    for i, (m, v) in enumerate(ordered):
        out[m] = v
        nxt = ordered[i + 1][0] if i + 1 < len(ordered) else None
        k = 1
        while k * 60 <= HR_CARRY_MAX.total_seconds():
            m2 = m + timedelta(minutes=k)
            if nxt is not None and m2 >= nxt:
                break
            if m2.astimezone(settings.tz).date() == tz_day:
                out[m2] = v
            k += 1
    return out


def cadence_per_minute(rows: list[Row], priority: list[str]) -> dict[datetime, float]:
    """Steps per UTC minute: each counted record spreads its steps evenly over its minutes.

    Records come through ``counted_values`` (ADR 0002): a lower-ranked source only contributes the
    part of its span that a higher-ranked one does not already cover, so the same walk written by
    Fit and Withings is never counted twice. Records longer than STEPS_MAX_SPAN are dropped first
    (they are totals, not cadence) so they do not hide the real ones.
    """
    usable = [
        r for r in rows if r.end is not None and timedelta(0) < r.end - r.start <= STEPS_MAX_SPAN
    ]
    out: dict[datetime, float] = defaultdict(float)
    for row, value, fraction in counted_values(usable, "value", priority)[0]:
        if fraction <= 0 or value <= 0 or row.end is None:
            continue
        span = (row.end - row.start).total_seconds()
        rate = value / span
        cursor = row.start
        while cursor < row.end:
            m = _minute(cursor)
            nxt = min(row.end, m + timedelta(minutes=1))
            out[m] += rate * (nxt - cursor).total_seconds()
            cursor = nxt
    return dict(out)


@dataclass
class DayPoints:
    total: int
    hr_points: int
    cadence_points: int
    active_minutes: int
    hr_max: int | None
    hr_source: str | None


def score_day(
    hr_by_minute: dict[datetime, float],
    cadence_by_minute: dict[datetime, float],
    hr_max: int | None,
) -> DayPoints:
    """Points of a day from the two per-minute series (pure function)."""
    total = hr_total = cad_total = active = 0
    for m in sorted(set(hr_by_minute) | set(cadence_by_minute)):
        hp = hr_points(hr_by_minute[m], hr_max) if hr_max and m in hr_by_minute else 0
        cp = cadence_points(cadence_by_minute[m]) if m in cadence_by_minute else 0
        pts = minute_points(hp, cp)
        hr_total += hp
        cad_total += cp
        total += pts
        active += 1 if pts else 0
    return DayPoints(total, hr_total, cad_total, active, hr_max, None)


_HR_MINUTES = text(
    """
    SELECT date_trunc('minute', h.ts) AS m, avg(h.value) AS v
    FROM health_sample h JOIN health_record r ON r.id = h.record_id
    WHERE h.type = 'HeartRate' AND r.deleted_at IS NULL AND h.local_date = :d
    GROUP BY 1 ORDER BY 1
    """
)


async def compute_day(session: AsyncSession, settings: Settings, day: date) -> DayPoints | None:
    """The day's points, or None when there is no heart-rate or step data at all that day."""
    hr_raw = {
        r.m.astimezone(UTC): float(r.v)
        for r in (await session.execute(_HR_MINUTES, {"d": day})).all()
    }
    steps = (
        await session.execute(
            select(
                HealthRecord.local_date,
                HealthRecord.start_ts,
                HealthRecord.end_ts,
                HealthRecord.source_package,
                HealthRecord.data,
            ).where(
                HealthRecord.type == "Steps",
                HealthRecord.deleted_at.is_(None),
                HealthRecord.local_date == day,
            )
        )
    ).all()
    if not hr_raw and not steps:
        return None
    hr_max, source = hr_max_for(settings, day)
    rows = [Row(ld, s, e, pkg, data) for ld, s, e, pkg, data in steps]
    result = score_day(
        carry_forward(hr_raw, day, settings),
        cadence_per_minute(rows, settings.source_priority_list),
        hr_max,
    )
    result.hr_source = source
    return result


async def recompute(session: AsyncSession, settings: Settings, days: Iterable[date]) -> int:
    """(Re)write the HeartPoints row of each day; a day with no data loses its row."""
    sig = config_signature(settings)
    rows: list[dict[str, Any]] = []
    empty: list[date] = []
    for day in sorted(set(days)):
        res = await compute_day(session, settings, day)
        if res is None:
            empty.append(day)
            continue
        rows.append(
            {
                "local_date": day,
                "type": HEART_POINTS_TYPE,
                "source": "computed",
                "sum_value": float(res.total),
                "count": res.active_minutes,
                "unit": "points",
                "detail": {
                    "method": "minute_max_of_hr_and_cadence",
                    "hr_points": res.hr_points,
                    "cadence_points": res.cadence_points,
                    "hr_max": res.hr_max,
                    "hr_max_source": res.hr_source,
                    "config": sig,
                },
                "snapshot_at": func.now(),
                "updated_at": func.now(),
            }
        )
    if rows:
        stmt = pg_insert(DailyMetric).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["local_date", "type", "source"],
            set_={
                c: stmt.excluded[c]
                for c in ("sum_value", "count", "unit", "detail", "snapshot_at", "updated_at")
            },
        )
        await session.execute(stmt)
    if empty:
        await session.execute(
            delete(DailyMetric).where(
                DailyMetric.type == HEART_POINTS_TYPE,
                DailyMetric.source == "computed",
                DailyMetric.local_date.in_(empty),
            )
        )
    return len(rows)


async def days_to_compute(session: AsyncSession, settings: Settings) -> list[date]:
    """Days with heart-rate or step data lacking points, or computed with other settings."""
    sig = config_signature(settings)
    have = {
        d: (detail or {}).get("config")
        for d, detail in (
            await session.execute(
                select(DailyMetric.local_date, DailyMetric.detail).where(
                    DailyMetric.type == HEART_POINTS_TYPE, DailyMetric.source == "computed"
                )
            )
        ).all()
    }
    candidates = {
        d
        for (d,) in (
            await session.execute(
                select(HealthRecord.local_date)
                .where(
                    HealthRecord.type.in_(("HeartRate", "Steps")), HealthRecord.deleted_at.is_(None)
                )
                .distinct()
            )
        ).all()
    }
    return sorted(d for d in candidates if have.get(d) != sig)

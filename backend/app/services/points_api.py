"""Read side of the Heart Points: series by week/month/year, the current week, the rules."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.errors import ApiError
from app.models import DailyMetric
from app.services import heartpoints as hp
from app.services.queries import MAX_POINTS, MAX_SERIES_DAYS, _span_days, bucket_start

Bucket = Literal["day", "week", "month", "year"]


DAILY_REFERENCE = hp.WEEKLY_GOAL / 7
"""Indicative points per day (goal / 7): a reference line, NOT a daily goal."""


def _start(day: date, bucket: Bucket) -> date:
    if bucket == "day":
        return day
    return date(day.year, 1, 1) if bucket == "year" else bucket_start(day, bucket)


def _next(start: date, bucket: Bucket) -> date:
    if bucket == "day":
        return start + timedelta(days=1)
    if bucket == "week":
        return start + timedelta(days=7)
    if bucket == "month":
        return (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return date(start.year + 1, 1, 1)


async def _daily(session: AsyncSession, first: date, last: date) -> dict[date, float]:
    rows = (
        await session.execute(
            select(DailyMetric.local_date, DailyMetric.sum_value).where(
                DailyMetric.type == hp.HEART_POINTS_TYPE,
                DailyMetric.source == "computed",
                DailyMetric.local_date.between(first, last),
            )
        )
    ).all()
    return {d: float(v or 0) for d, v in rows}


DETAIL_KEYS = (
    "hr_points",
    "hr_points_ungated",
    "cadence_points",
    "points_by_hr",
    "points_by_cadence",
    "minutes_active",
    "minutes_by_session",
    "minutes_by_steps",
)
"""Diagnostic counters stored per day in ``daily_metric.detail`` and summed per bucket."""


def _detail_of(detail: dict[str, Any] | None) -> dict[str, int]:
    d = detail or {}
    return {k: int(d.get(k) or 0) for k in DETAIL_KEYS}


async def _daily_detail(
    session: AsyncSession, first: date, last: date
) -> dict[date, dict[str, int]]:
    rows = (
        await session.execute(
            select(DailyMetric.local_date, DailyMetric.detail).where(
                DailyMetric.type == hp.HEART_POINTS_TYPE,
                DailyMetric.source == "computed",
                DailyMetric.local_date.between(first, last),
            )
        )
    ).all()
    return {d: _detail_of(detail) for d, detail in rows}


def _total(days: dict[date, float]) -> dict[str, Any]:
    return {"total": sum(days.values()), "days": len(days)}


async def points_series(
    session: AsyncSession, settings: Settings, first: date, last: date, bucket: Bucket
) -> dict[str, Any]:
    if last < first:
        raise ApiError(422, "invalid_range", "`to` must not precede `from`")
    span = _span_days(first, last)
    if span > MAX_SERIES_DAYS:
        raise ApiError(422, "range_too_long", f"At most {MAX_SERIES_DAYS} days")
    # like the other charts: too many points -> a wider bucket, and the answer says so
    coarsened = bucket == "day" and span > MAX_POINTS
    if coarsened:
        bucket = "week"
    today = datetime.now(settings.tz).date()
    daily = await _daily(session, first, last)
    details = await _daily_detail(session, first, last)
    sums: dict[date, float] = {}
    counts: dict[date, int] = {}
    detail_sums: dict[date, dict[str, int]] = {}
    for d, v in daily.items():
        key = _start(d, bucket)
        sums[key] = sums.get(key, 0.0) + v
        counts[key] = counts.get(key, 0) + 1
        acc = detail_sums.setdefault(key, dict.fromkeys(DETAIL_KEYS, 0))
        for k, n in details.get(d, {}).items():
            acc[k] += n
    points: list[dict[str, Any]] = []
    cursor = _start(first, bucket)
    while cursor <= last:
        end = _next(cursor, bucket) - timedelta(days=1)
        points.append(
            {
                "t": cursor.isoformat(),
                "v": sums.get(cursor, 0.0),
                "days": counts.get(cursor, 0),
                "detail": detail_sums.get(cursor, dict.fromkeys(DETAIL_KEYS, 0)),
                # a bucket counts for "goal reached or not" only when it is whole, inside the
                # range and already over (the running week is still being earned)
                "complete": cursor >= first and end <= last and end < today,
            }
        )
        cursor = _next(cursor, bucket)
    complete = [p for p in points if p["complete"]]
    over = sum(1 for p in complete if p["v"] >= hp.WEEKLY_GOAL) if bucket == "week" else None
    days_over = sum(1 for p in complete if p["v"] >= DAILY_REFERENCE) if bucket == "day" else None
    prev_last = first - timedelta(days=1)
    prev_first = prev_last - timedelta(days=span - 1)
    return {
        "from": first,
        "to": last,
        "bucket": bucket,
        "weekly_goal": hp.WEEKLY_GOAL,
        "daily_reference": DAILY_REFERENCE,
        "coarsened": coarsened,
        "timezone": settings.local_timezone,
        "hr_configured": hp.hr_max_for(settings, today)[0] is not None,
        "points": points,
        "summary": {
            **_total(daily),
            "buckets_complete": len(complete),
            "weeks_over_goal": over,
            "days_over_reference": days_over,
        },
        "previous_from": prev_first,
        "previous_to": prev_last,
        "previous_summary": _total(await _daily(session, prev_first, prev_last)),
    }


async def points_week(session: AsyncSession, settings: Settings, day: date) -> dict[str, Any]:
    monday = day - timedelta(days=day.weekday())
    sunday = monday + timedelta(days=6)
    today = datetime.now(settings.tz).date()
    rows = (
        await session.execute(
            select(DailyMetric.local_date, DailyMetric.sum_value, DailyMetric.detail).where(
                DailyMetric.type == hp.HEART_POINTS_TYPE,
                DailyMetric.source == "computed",
                DailyMetric.local_date.between(monday, sunday),
            )
        )
    ).all()
    by_day = {d: (float(v or 0), detail or {}) for d, v, detail in rows}
    days = []
    for i in range(7):
        d = monday + timedelta(days=i)
        total, detail = by_day.get(d, (None, {}))
        days.append(
            {
                "date": d,
                "points": total,
                "hr_points": detail.get("hr_points") if total is not None else None,
                "cadence_points": detail.get("cadence_points") if total is not None else None,
                "detail": _detail_of(detail) if total is not None else None,
            }
        )
    total = sum(v for v, _ in by_day.values())
    is_current = monday <= today <= sunday
    # days left to earn points, today included; a week in the past has none, a future one has 7
    days_left = (sunday - today).days + 1 if is_current else (0 if sunday < today else 7)
    return {
        "week_start": monday,
        "week_end": sunday,
        "is_current": is_current,
        "total": total,
        "goal": hp.WEEKLY_GOAL,
        "remaining": max(0.0, hp.WEEKLY_GOAL - total),
        "reached": total >= hp.WEEKLY_GOAL,
        "days_left": days_left,
        "days": days,
        "hr_configured": hp.hr_max_for(settings, today)[0] is not None,
    }


def describe_points_rules(settings: Settings) -> dict[str, Any]:
    """The Heart Points rules, from the constants the calculation uses."""
    today = datetime.now(settings.tz).date()
    hr_max, source = hp.hr_max_for(settings, today)
    return {
        "heart_rate": {
            "moderate_pct": hp.HR_MODERATE_PCT,
            "vigorous_pct": hp.HR_VIGOROUS_PCT,
            "hr_max": hr_max,
            "hr_max_source": source,
            "configured": hr_max is not None,
            "carry_max_minutes": int(hp.HR_CARRY_MAX.total_seconds() // 60),
            "formula": {"intercept": hp.HR_MAX_INTERCEPT, "slope": hp.HR_MAX_SLOPE},
            "needs_active_minute": True,
        },
        "active_minute": {
            "min_steps": hp.ACTIVE_CADENCE_MIN,
            "exercise_session": True,
        },
        "rules_version": hp.RULES_VERSION,
        "cadence": {
            "moderate_steps": hp.CADENCE_MODERATE,
            "vigorous_steps": hp.CADENCE_VIGOROUS,
            "max_record_minutes": int(hp.STEPS_MAX_SPAN.total_seconds() // 60),
        },
        "points": {"moderate": hp.MODERATE_POINTS, "vigorous": hp.VIGOROUS_POINTS},
        "combine": "max",
        "met_used": False,
        "weekly_goal": hp.WEEKLY_GOAL,
        "daily_reference": DAILY_REFERENCE,
        "week_starts": "monday",
        "timezone": settings.local_timezone,
    }

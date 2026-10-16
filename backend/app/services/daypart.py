"""Heart rate split into day and night (read-only, computed on the fly, no stored state).

Night = HeartRate samples inside a recorded, non-deleted SleepSession. A local day that has no
sleep session at all falls back to the fixed window 23:00 (previous evening) - 07:00 local.
A night belongs to the day it ends on, like the sleep itself (PROJECT_GUIDE 5.2.3).
Day = every other sample (grouped by the sample's own local day), minus the real workouts and the
30 minutes after them (ADR 0006) unless the caller asks to include them. The night always wins.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from statistics import mean
from typing import Literal, cast
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.dash_schemas import (
    DaypartPoint,
    DaypartResponse,
    DaypartStats,
    DaypartSummary,
    NightInterval,
    WorkoutInterval,
)
from app.errors import ApiError
from app.models import HealthRecord
from app.services.analytics import previous_range
from app.services.queries import MAX_SERIES_DAYS, _span_days, bucket_start, local_bounds
from app.services.workouts import classify, recovery_end

FIXED_START = time(23, 0)
FIXED_END = time(7, 0)
FIXED_WINDOW = "23:00-07:00"


@dataclass
class Span:
    start: datetime
    end: datetime
    day: date  # the day the night ends on
    source: str  # "sleep" | "fixed"


def fixed_night(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """The fallback night of ``day``: 23:00 the evening before until 07:00 (local, DST-aware)."""
    start = datetime.combine(day - timedelta(days=1), FIXED_START, tzinfo=tz)
    end = datetime.combine(day, FIXED_END, tzinfo=tz)
    return start.astimezone(UTC), end.astimezone(UTC)


def merge_spans(spans: list[Span]) -> list[Span]:
    """Union of overlapping spans (two apps often log the same night). Keeps the latest day."""
    out: list[Span] = []
    for s in sorted(spans, key=lambda x: (x.start, x.end)):
        if out and s.start < out[-1].end:
            last = out[-1]
            last.end = max(last.end, s.end)
            last.day = max(last.day, s.day)
            if s.source == "sleep":
                last.source = "sleep"
        else:
            out.append(Span(s.start, s.end, s.day, s.source))
    return out


async def _sleep_spans(session: AsyncSession, first: date, last: date) -> list[Span]:
    rows = (
        await session.execute(
            select(HealthRecord.start_ts, HealthRecord.end_ts, HealthRecord.local_date).where(
                HealthRecord.type == "SleepSession",
                HealthRecord.deleted_at.is_(None),
                HealthRecord.end_ts.is_not(None),
                HealthRecord.local_date.between(first, last),
            )
        )
    ).all()
    return [Span(s, e, d, "sleep") for s, e, d in rows if e is not None and e > s]


# width_bucket() is a binary search over the (sorted, non-overlapping) interval starts: every sample
# finds its night / workout in O(log n) instead of joining 500k samples against the intervals.
_SQL = text(
    """
    WITH c AS (
        SELECT h.value, h.local_date AS ld, extract(epoch FROM h.ts)::float8 AS ep,
               width_bucket(extract(epoch FROM h.ts)::float8, CAST(:starts AS float8[])) AS i,
               width_bucket(extract(epoch FROM h.ts)::float8, CAST(:xstarts AS float8[])) AS j
        FROM health_sample h
        JOIN health_record r ON r.id = h.record_id
        WHERE h.type = 'HeartRate' AND r.deleted_at IS NULL AND h.ts >= :s AND h.ts < :e
    ), d AS (
        SELECT value, ld,
               CASE WHEN i > 0 AND ep < (CAST(:ends AS float8[]))[i] THEN i END AS i2,
               CASE WHEN j > 0 AND ep < (CAST(:xends AS float8[]))[j] THEN j END AS j2
        FROM c
    )
    SELECT coalesce((CAST(:dates AS date[]))[i2], ld) AS day, (i2 IS NOT NULL) AS night,
           (i2 IS NULL AND j2 IS NOT NULL) AS workout, avg(value) AS v, count(*) AS n
    FROM d GROUP BY 1, 2, 3
    """
)


@dataclass
class DayStats:
    day_avg: float | None = None  # outside nights and workouts
    day_n: int = 0
    night_avg: float | None = None
    night_n: int = 0
    work_avg: float | None = None  # inside a real workout (or its 30 min recovery), not at night
    work_n: int = 0

    def daytime(self, include_workouts: bool) -> tuple[float | None, int]:
        """The daytime mean and its sample count, with or without the workouts."""
        if not include_workouts or self.work_n == 0:
            return self.day_avg, self.day_n
        n = self.day_n + self.work_n
        total = (self.day_avg or 0.0) * self.day_n + (self.work_avg or 0.0) * self.work_n
        return total / n, n


def _merge_intervals(spans: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    out: list[tuple[datetime, datetime]] = []
    for start, end in sorted(spans):
        if out and start < out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


async def _workout_spans(
    session: AsyncSession, settings: Settings, first: date, last: date
) -> list[tuple[datetime, datetime, datetime]]:
    """Real workouts near the range as (start, end, end + 30 min recovery)."""
    found = await classify(session, settings, first - timedelta(days=1), last + timedelta(days=1))
    return [(c.workout.start_ts, c.workout.end, recovery_end(c)) for c in found if c.is_real]


async def _compute(
    session: AsyncSession, settings: Settings, first: date, last: date
) -> tuple[list[Span], dict[date, DayStats], list[tuple[datetime, datetime, datetime]]]:
    tz = settings.tz
    # one day past the range: a night that starts on `last` evening belongs to the next day
    spans = await _sleep_spans(session, first, last + timedelta(days=1))
    with_sleep = {s.day for s in spans}
    day = first
    while day <= last + timedelta(days=1):
        if day not in with_sleep:
            start, end = fixed_night(day, tz)
            spans.append(Span(start, end, day, "fixed"))
        day += timedelta(days=1)
    merged = merge_spans(spans)
    workouts = await _workout_spans(session, settings, first, last)
    excluded = _merge_intervals([(s, rec) for s, _e, rec in workouts])
    lo, hi = local_bounds(first, last, tz)
    lo = min([lo, *[s.start for s in merged]])
    hi = max([hi, *[s.end for s in merged]])
    # element 0 is a sentinel so the arrays are never empty
    result = await session.execute(
        _SQL,
        {
            "starts": [0.0, *[s.start.timestamp() for s in merged]],
            "ends": [0.0, *[s.end.timestamp() for s in merged]],
            "dates": [date(1970, 1, 1), *[s.day for s in merged]],
            "xstarts": [0.0, *[s.timestamp() for s, _ in excluded]],
            "xends": [0.0, *[e.timestamp() for _, e in excluded]],
            "s": lo,
            "e": hi,
        },
    )
    per_day: dict[date, DayStats] = defaultdict(DayStats)
    for d, night, workout, v, n in result.all():
        if not first <= d <= last:
            continue
        entry = per_day[d]
        if night:
            entry.night_avg, entry.night_n = float(v), int(n)
        elif workout:
            entry.work_avg, entry.work_n = float(v), int(n)
        else:
            entry.day_avg, entry.day_n = float(v), int(n)
    return merged, dict(per_day), workouts


def _stats(values: list[tuple[float | None, int]]) -> DaypartStats:
    present = [(v, n) for v, n in values if v is not None]
    if not present:
        return DaypartStats(avg=None, days=0, samples=0)
    return DaypartStats(
        avg=mean(v for v, _ in present), days=len(present), samples=sum(n for _, n in present)
    )


def summarize_days(days: dict[date, DayStats], include_workouts: bool = False) -> DaypartSummary:
    return DaypartSummary(
        day=_stats([d.daytime(include_workouts) for d in days.values()]),
        night=_stats([(d.night_avg, d.night_n) for d in days.values()]),
    )


def bucket_points(
    days: dict[date, DayStats], bucket: str, include_workouts: bool = False
) -> list[DaypartPoint]:
    groups: dict[date, list[DayStats]] = defaultdict(list)
    for d, entry in days.items():
        groups[bucket_start(d, bucket)].append(entry)
    out: list[DaypartPoint] = []
    for key in sorted(groups):
        entries = groups[key]
        daytime = [e.daytime(include_workouts) for e in entries]
        dn = sum(n for _, n in daytime)
        nn = sum(e.night_n for e in entries)
        out.append(
            DaypartPoint(
                t=key.isoformat(),
                day=sum((v or 0) * n for v, n in daytime) / dn if dn else None,
                night=sum((e.night_avg or 0) * e.night_n for e in entries) / nn if nn else None,
                day_n=dn,
                night_n=nn,
            )
        )
    return out


async def daypart(
    session: AsyncSession,
    settings: Settings,
    first: date,
    last: date,
    bucket: Literal["day", "week", "month"],
    include_workouts: bool = False,
) -> DaypartResponse:
    if last < first:
        raise ApiError(422, "invalid_range", "`to` must not precede `from`")
    if _span_days(first, last) > MAX_SERIES_DAYS:
        raise ApiError(422, "range_too_long", f"At most {MAX_SERIES_DAYS} days")
    spans, days, workouts = await _compute(session, settings, first, last)
    pf, pl = previous_range(first, last)
    _, prev_days, _ = await _compute(session, settings, pf, pl)
    lo, hi = local_bounds(first, last, settings.tz)
    # fixed nights are only worth drawing where there is data for that day
    nights = [
        NightInterval(
            date=s.day,
            start=s.start,
            end=s.end,
            source=cast(Literal["sleep", "fixed"], s.source),
        )
        for s in spans
        if first <= s.day <= last and (s.source == "sleep" or s.day in days)
    ]
    return DaypartResponse(
        from_=first,
        to=last,
        bucket=bucket,
        timezone=settings.local_timezone,
        fixed_window=FIXED_WINDOW,
        nights=nights,
        include_workouts=include_workouts,
        workouts=[
            WorkoutInterval(start=s, end=e, recovery_end=r)
            for s, e, r in sorted(workouts)
            if r > lo and s < hi
        ],
        points=bucket_points(days, bucket, include_workouts),
        summary=summarize_days(days, include_workouts),
        previous_from=pf,
        previous_to=pl,
        previous_summary=summarize_days(prev_days, include_workouts),
    )

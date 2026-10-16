"""Which exercise sessions are "real workouts" (ADR 0006). Read-only except the override.

Rules, in this order (the first one that applies decides):
  1. the user's manual verdict (override) always wins;
  2. exercise type in ``NOT_REAL_TYPES`` (today: walking) -> not real;
  3. shorter than ``MIN_DURATION`` (15 minutes, whatever the type) -> not real;
  4. otherwise -> real.
``describe_rules()`` turns these same constants into what the dashboard shows on the "Rules" panel,
so the text and the code cannot drift apart. Heart-rate coverage, GPS and who started the session
are still computed, but only as information (badges): Google derives GPS even for activities the
user never started, so they do not tell workouts apart (ADR 0006). Records are never loaded with
their ``data``: a GPS route can be 50 000 points, so only the flags we need are selected.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import ExerciseOverride, HealthRecord, HealthSample
from app.services.daily import Coverage, rank_sources

# --- the rule: ONE place to refine it ------------------------------------------------------
NOT_REAL_TYPES = frozenset({"WALKING"})
"""Exercise types that are NOT real workouts. Everything else (running, cycling, hiking...) is."""

MIN_DURATION = timedelta(minutes=15)
"""A session shorter than this is not real, whatever its type (exactly this long is real)."""

# --- information shown next to each session (not part of the rule) --------------------------
HR_COVERAGE_MIN = 0.5
"""Share of the session minutes with a heart-rate sample: the "heart rate present" badge."""

USER_STARTED_METHODS = frozenset({"active", "manual"})
"""recording_method values that mean "the user started it" (automatic/unknown do not)."""

RECOVERY_AFTER_S = 30 * 60
"""Samples up to 30 minutes after a real workout are excluded from the daytime heart rate."""

DUPLICATE_OVERLAP = 0.5
"""Two sessions overlapping more than this are the same workout logged by two apps."""


Rule = Literal["type", "duration", "ok"]
"""Which rule decided the automatic verdict ("ok" = no exclusion rule applied -> real)."""


def evaluate_rules(exercise_type: str, duration_s: float) -> Rule:
    """The automatic verdict, in order: excluded type, then too short, else real."""
    if exercise_type in NOT_REAL_TYPES:
        return "type"
    if duration_s < MIN_DURATION.total_seconds():
        return "duration"
    return "ok"


def describe_rules() -> dict[str, Any]:
    """The active rules in evaluation order, built from the constants the classifier uses."""
    return {
        "rules": [
            {"id": "override", "params": {}},
            {"id": "type", "params": {"types": sorted(NOT_REAL_TYPES)}},
            {"id": "duration", "params": {"min_minutes": int(MIN_DURATION.total_seconds() // 60)}},
            {"id": "default", "params": {}},
        ],
        "daytime_hr": {
            "excludes": "real_workouts",
            "recovery_minutes": RECOVERY_AFTER_S // 60,
        },
        "signals": {
            "hr_min_share": HR_COVERAGE_MIN,
            "user_started_methods": sorted(USER_STARTED_METHODS),
            "informative_only": True,
        },
    }


@dataclass(frozen=True)
class Workout:
    id: int
    hc_id: str
    start_ts: datetime
    end_ts: datetime | None
    local_date: date
    source_package: str
    recording_method: str
    exercise_type: str
    title: str | None
    has_route: bool

    @property
    def end(self) -> datetime:
        return self.end_ts or self.start_ts

    @property
    def duration_s(self) -> float:
        return (self.end - self.start_ts).total_seconds()


@dataclass
class Classified:
    workout: Workout
    members: list[Workout] = field(default_factory=list)  # the copies merged into this one
    hr_coverage: float | None = None
    has_gps: bool = False
    user_started: bool = False
    override: bool | None = None

    @property
    def has_hr(self) -> bool:
        return self.hr_coverage is not None and self.hr_coverage >= HR_COVERAGE_MIN

    @property
    def auto_rule(self) -> Rule:
        return evaluate_rules(self.workout.exercise_type, self.workout.duration_s)

    @property
    def auto_real(self) -> bool:
        return self.auto_rule == "ok"

    @property
    def is_real(self) -> bool:
        return self.override if self.override is not None else self.auto_real


async def load_workouts(session: AsyncSession, first: date, last: date) -> list[Workout]:
    rows = (
        await session.execute(
            select(
                HealthRecord.id,
                HealthRecord.hc_id,
                HealthRecord.start_ts,
                HealthRecord.end_ts,
                HealthRecord.local_date,
                HealthRecord.source_package,
                HealthRecord.recording_method,
                HealthRecord.data["exercise_type"].astext,
                HealthRecord.data["title"].astext,
                HealthRecord.data.has_key("route"),
            ).where(
                HealthRecord.type == "ExerciseSession",
                HealthRecord.deleted_at.is_(None),
                HealthRecord.local_date.between(first, last),
            )
        )
    ).all()
    return [
        Workout(i, h, s, e, d, pkg, method, etype or "UNKNOWN", title, bool(route))
        for i, h, s, e, d, pkg, method, etype, title, route in rows
    ]


def dedupe_groups(
    rows: Sequence[Workout], settings: Settings
) -> list[tuple[Workout, list[Workout]]]:
    """A workout logged by two apps appears once: best-ranked copy wins (tie: has a route).

    Returns (kept copy, all copies including it), newest first.
    """
    counts: dict[str, float] = defaultdict(float)
    for r in rows:
        counts[r.source_package] += 1
    ranks = rank_sources(counts, settings.source_priority_list)
    coverage = Coverage()
    kept: list[tuple[Workout, list[Workout]]] = []
    for r in sorted(rows, key=lambda r: (ranks[r.source_package], not r.has_route)):
        s, e = r.start_ts.timestamp(), r.end.timestamp()
        if e > s and coverage.overlap(s, e) / (e - s) > DUPLICATE_OVERLAP:
            best = max(
                kept,
                key=lambda g: max(
                    0.0,
                    min(e, g[0].end.timestamp()) - max(s, g[0].start_ts.timestamp()),
                ),
                default=None,
            )
            if best is not None:
                best[1].append(r)
            continue
        kept.append((r, [r]))
        coverage.add_all([(s, e)])
    kept.sort(key=lambda g: g[0].start_ts, reverse=True)
    return kept


async def hr_coverage(session: AsyncSession, workouts: Sequence[Workout]) -> dict[int, float]:
    """Share of each session's minutes with at least one HeartRate sample (0..1)."""
    if not workouts:
        return {}
    rows = (
        await session.execute(
            select(
                HealthRecord.id,
                func.count(func.distinct(func.date_trunc("minute", HealthSample.ts))),
            )
            .join(
                HealthSample,
                (HealthSample.type == "HeartRate")
                & (HealthSample.ts >= HealthRecord.start_ts)
                & (HealthSample.ts <= HealthRecord.end_ts),
            )
            .where(HealthRecord.id.in_([w.id for w in workouts]))
            .group_by(HealthRecord.id)
        )
    ).all()
    minutes = {rid: int(n) for rid, n in rows}
    out: dict[int, float] = {}
    for w in workouts:
        total = max(1, -(-int(w.duration_s) // 60))
        out[w.id] = min(1.0, minutes.get(w.id, 0) / total)
    return out


async def overrides_for(session: AsyncSession, hc_ids: Sequence[str]) -> dict[str, bool]:
    if not hc_ids:
        return {}
    rows = (
        await session.execute(
            select(ExerciseOverride.hc_id, ExerciseOverride.is_real).where(
                ExerciseOverride.hc_id.in_(list(hc_ids))
            )
        )
    ).all()
    return {h: v for h, v in rows}


async def classify(
    session: AsyncSession, settings: Settings, first: date, last: date
) -> list[Classified]:
    """Every distinct workout of the range with its signals and verdict, newest first."""
    groups = dedupe_groups(await load_workouts(session, first, last), settings)
    kept = [g[0] for g in groups]
    coverage = await hr_coverage(session, kept)
    overrides = await overrides_for(session, [m.hc_id for _, members in groups for m in members])
    out: list[Classified] = []
    for w, members in groups:
        verdicts = [overrides[m.hc_id] for m in members if m.hc_id in overrides]
        out.append(
            Classified(
                workout=w,
                members=members,
                hr_coverage=coverage.get(w.id),
                has_gps=any(m.has_route for m in members),
                user_started=any(m.recording_method in USER_STARTED_METHODS for m in members),
                # the kept copy's own verdict wins, else any copy's
                override=overrides.get(w.hc_id, verdicts[0] if verdicts else None),
            )
        )
    return out


def recovery_end(c: Classified) -> datetime:
    return c.workout.end + timedelta(seconds=RECOVERY_AFTER_S)


async def set_override(
    session: AsyncSession, settings: Settings, record_id: int, value: bool | None
) -> Classified | None:
    """Store (or clear, value=None) the manual verdict for a workout and all its copies.

    Returns the workout as classified afterwards, or None if no such live workout exists.
    """
    day = (
        await session.execute(
            select(HealthRecord.local_date).where(
                HealthRecord.id == record_id,
                HealthRecord.type == "ExerciseSession",
                HealthRecord.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if day is None:
        return None
    window = (day - timedelta(days=1), day + timedelta(days=1))
    group = next(
        (
            c
            for c in await classify(session, settings, *window)
            if any(m.id == record_id for m in c.members)
        ),
        None,
    )
    if group is None:
        return None
    hc_ids = [m.hc_id for m in group.members]
    if value is None:
        await session.execute(delete(ExerciseOverride).where(ExerciseOverride.hc_id.in_(hc_ids)))
    else:
        stmt = pg_insert(ExerciseOverride).values([{"hc_id": h, "is_real": value} for h in hc_ids])
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=["hc_id"], set_={"is_real": value, "updated_at": func.now()}
            )
        )
    await session.commit()
    group.override = value
    return group

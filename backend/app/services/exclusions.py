"""Manual exclusion of single measures (ADR 0011).

Only point measures and sessions can be excluded (never whole days, never cumulative totals).
Excluding writes ``record_exclusion`` rows and recomputes just the days those records touch;
restoring deletes the rows and recomputes the same days. Nothing in ``health_record`` changes.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.dash_schemas import ExcludeResult, ExclusionItem, MeasureItem
from app.errors import ApiError
from app.health_types import SPECS
from app.models import HealthRecord, RecordExclusion
from app.services.daily import rank_sources, recompute_days
from app.services.ingest import INGEST_LOCK_KEY
from app.services.visibility import not_excluded

# type -> shape. Instants are the same measure when they share the instant; sessions when they
# overlap by more than half (the same rules the daily de-duplication uses).
EXCLUDABLE: dict[str, str] = {
    "Weight": "instant",
    "BloodPressure": "instant",
    "OxygenSaturation": "instant",
    "RestingHeartRate": "instant",
    "HeartRateVariabilityRmssd": "instant",
    "SleepSession": "session",
    "ExerciseSession": "session",
}
MAX_REASON = 200
MAX_WINDOW_DAYS = 400
SESSION_TWIN_OVERLAP = 0.5


@dataclass
class Rec:
    id: int
    hc_id: str
    type: str
    start: datetime
    end: datetime | None
    local_date: date
    source: str
    data: dict[str, Any]

    @property
    def seconds(self) -> float:
        return ((self.end or self.start) - self.start).total_seconds()


def is_twin(a: Rec, b: Rec) -> bool:
    """Same measure seen by two apps?"""
    if EXCLUDABLE[a.type] == "instant":
        return a.start == b.start
    lo, hi = max(a.start, b.start), min(a.end or a.start, b.end or b.start)
    shorter = min(a.seconds, b.seconds)
    return shorter > 0 and (hi - lo).total_seconds() / shorter > SESSION_TWIN_OVERLAP


def cluster(recs: list[Rec]) -> list[list[Rec]]:
    """Group copies of one measure. Input of a single type, any order."""
    groups: list[list[Rec]] = []
    for r in sorted(recs, key=lambda r: (r.start, r.id)):
        for g in reversed(groups[-3:]):  # copies start at (almost) the same time
            if is_twin(g[0], r):
                g.append(r)
                break
        else:
            groups.append([r])
    return groups


def _values(r: Rec) -> tuple[float | None, float | None, str | None, str | None]:
    """(value, second value, unit, label) of a record, as the dashboard formats them."""
    unit = SPECS[r.type].unit
    if r.type == "BloodPressure":
        return r.data.get("systolic"), r.data.get("diastolic"), unit, None
    if r.type == "SleepSession":
        return r.seconds, None, "s", r.data.get("title")
    if r.type == "ExerciseSession":
        return r.seconds, None, "s", r.data.get("title") or r.data.get("exercise_type")
    return r.data.get("value"), None, unit, None


def _item(group: list[Rec], settings: Settings) -> MeasureItem:
    counts: dict[str, float] = defaultdict(float)
    for r in group:
        counts[r.source] += 1
    ranks = rank_sources(counts, settings.source_priority_list)
    best = min(group, key=lambda r: (ranks[r.source], r.id))
    value, value2, unit, label = _values(best)
    return MeasureItem(
        ids=sorted(r.id for r in group),
        type=best.type,
        start=best.start,
        end=best.end,
        local_date=best.local_date,
        value=value,
        value2=value2,
        unit=unit,
        label=label,
        sources=sorted({r.source for r in group}),
    )


def _rec(row: Any) -> Rec:
    return Rec(
        row.id,
        row.hc_id,
        row.type,
        row.start_ts,
        row.end_ts,
        row.local_date,
        row.source_package,
        row.data,
    )


def check_type(type_: str) -> None:
    if type_ not in EXCLUDABLE:
        raise ApiError(
            422,
            "type_not_excludable",
            f"Only point measures and sessions can be excluded: {', '.join(sorted(EXCLUDABLE))}",
        )


async def list_measures(
    session: AsyncSession, settings: Settings, type_: str, first: date, last: date
) -> list[MeasureItem]:
    """The individual measures (copies merged) of a period: what a chart point aggregates."""
    check_type(type_)
    if last < first or (last - first).days + 1 > MAX_WINDOW_DAYS:
        raise ApiError(422, "invalid_range", f"A period of 1 to {MAX_WINDOW_DAYS} days is required")
    rows = (
        await session.execute(
            select(HealthRecord).where(
                HealthRecord.type == type_,
                HealthRecord.deleted_at.is_(None),
                not_excluded(),
                HealthRecord.local_date.between(first, last),
            )
        )
    ).scalars()
    groups = cluster([_rec(r) for r in rows])
    return sorted((_item(g, settings) for g in groups), key=lambda m: m.start, reverse=True)


async def exclude(
    session: AsyncSession, settings: Settings, record_id: int, reason: str | None
) -> ExcludeResult:
    await session.execute(select(func.pg_advisory_xact_lock(INGEST_LOCK_KEY)))
    row = (
        await session.execute(
            select(HealthRecord).where(
                HealthRecord.id == record_id, HealthRecord.deleted_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise ApiError(404, "not_found", "No such measure")
    check_type(row.type)
    target = _rec(row)

    existing = (
        await session.execute(
            select(RecordExclusion.group_id).where(
                RecordExclusion.type == target.type, RecordExclusion.hc_id == target.hc_id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:  # idempotent: excluding twice is not an error
        group_id = existing
        twins = await _group_records(session, group_id)
        return await _result(session, settings, group_id, twins, touched_days=0)

    near = (
        await session.execute(
            select(HealthRecord).where(
                HealthRecord.type == target.type,
                HealthRecord.deleted_at.is_(None),
                not_excluded(),
                HealthRecord.local_date.between(
                    target.local_date - timedelta(days=1), target.local_date + timedelta(days=1)
                ),
            )
        )
    ).scalars()
    twins = [target] + [r for r in map(_rec, near) if r.id != target.id and is_twin(target, r)]

    group_id = uuid.uuid4()
    clean_reason = (reason or "").strip()[:MAX_REASON] or None
    stmt = pg_insert(RecordExclusion).values(
        [
            {"type": t.type, "hc_id": t.hc_id, "group_id": group_id, "reason": clean_reason}
            for t in twins
        ]
    )
    await session.execute(stmt.on_conflict_do_nothing(index_elements=["type", "hc_id"]))
    days = {(t.type, t.local_date) for t in twins}
    await recompute_days(session, days, settings)
    return await _result(session, settings, group_id, twins, touched_days=len(days))


async def _group_records(session: AsyncSession, group_id: uuid.UUID) -> list[Rec]:
    rows = (
        await session.execute(
            select(HealthRecord)
            .join(
                RecordExclusion,
                (RecordExclusion.type == HealthRecord.type)
                & (RecordExclusion.hc_id == HealthRecord.hc_id),
            )
            .where(RecordExclusion.group_id == group_id)
        )
    ).scalars()
    return [_rec(r) for r in rows]


async def _result(
    session: AsyncSession,
    settings: Settings,
    group_id: uuid.UUID,
    recs: list[Rec],
    touched_days: int,
) -> ExcludeResult:
    return ExcludeResult(
        group_id=group_id, records=len(recs), days=touched_days, measure=_item(recs, settings)
    )


async def restore(session: AsyncSession, settings: Settings, group_id: uuid.UUID) -> int:
    await session.execute(select(func.pg_advisory_xact_lock(INGEST_LOCK_KEY)))
    recs = await _group_records(session, group_id)
    gone = (
        await session.execute(
            delete(RecordExclusion)
            .where(RecordExclusion.group_id == group_id)
            .returning(RecordExclusion.hc_id)
        )
    ).all()
    if not gone:
        raise ApiError(404, "not_found", "No such exclusion")
    days = {(r.type, r.local_date) for r in recs}
    await recompute_days(session, days, settings)  # records missing from the DB just have no day
    return len(days)


async def list_exclusions(session: AsyncSession, settings: Settings) -> list[ExclusionItem]:
    rows = (
        await session.execute(
            select(RecordExclusion, HealthRecord)
            .outerjoin(
                HealthRecord,
                (RecordExclusion.type == HealthRecord.type)
                & (RecordExclusion.hc_id == HealthRecord.hc_id),
            )
            .order_by(RecordExclusion.created_at.desc())
        )
    ).all()
    groups: dict[uuid.UUID, list[tuple[RecordExclusion, HealthRecord | None]]] = defaultdict(list)
    for ex, rec in rows:
        groups[ex.group_id].append((ex, rec))
    out: list[ExclusionItem] = []
    for gid, members in groups.items():
        present = [_rec(r) for _, r in members if r is not None]
        ex0 = members[0][0]
        live = [r for _, r in members if r is not None and r.deleted_at is None]
        if not present:  # the record is gone from the DB altogether: still listed, restorable
            out.append(
                ExclusionItem(
                    group_id=gid,
                    type=ex0.type,
                    start=None,
                    end=None,
                    local_date=None,
                    value=None,
                    value2=None,
                    unit=SPECS[ex0.type].unit if ex0.type in SPECS else None,
                    label=None,
                    sources=[],
                    reason=ex0.reason,
                    created_at=ex0.created_at,
                    state="missing",
                )
            )
            continue
        item = _item(present, settings)
        out.append(
            ExclusionItem(
                group_id=gid,
                type=item.type,
                start=item.start,
                end=item.end,
                local_date=item.local_date,
                value=item.value,
                value2=item.value2,
                unit=item.unit,
                label=item.label,
                sources=item.sources,
                reason=ex0.reason,
                created_at=ex0.created_at,
                state="present" if live else "deleted_in_hc",
            )
        )
    return sorted(out, key=lambda e: e.created_at, reverse=True)

"""Ingest use-cases. Each function runs in ONE transaction; the caller commits.

Logging policy: only counts, types and ids are ever logged, never values.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from datetime import UTC, date, datetime
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import delete, func, insert, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.health_types import SPECS, DailyKind
from app.models import DailyMetric, Device, HealthRecord, HealthSample, SyncRun
from app.schemas import (
    DailyAggregateItem,
    DailyAggregatesBatch,
    DailyAggregatesResult,
    DeletionItem,
    DeletionsBatch,
    DeletionsResult,
    DeviceMeta,
    RecordIn,
    RecordsBatch,
    RecordsResult,
    Rejection,
    SyncReport,
    describe_validation_error,
)
from app.services.daily import recompute_days
from app.timeutil import local_date

log = logging.getLogger("sbh.ingest")

# Serialises all ingest writes: single-user volumes make this free, and it makes the
# read-modify-write of daily_metric race-free.
INGEST_LOCK_KEY = 7_421_001

TypeDay = tuple[str, date]


async def _lock(session: AsyncSession) -> None:
    await session.execute(select(func.pg_advisory_xact_lock(INGEST_LOCK_KEY)))


async def register_sync(
    session: AsyncSession,
    *,
    token_id: uuid.UUID,
    device_id: uuid.UUID,
    sync_id: uuid.UUID,
    meta: DeviceMeta | None,
    now: datetime,
) -> None:
    values = meta.model_dump(exclude_none=True) if meta else {}
    dev = pg_insert(Device).values(id=device_id, first_seen_at=now, last_seen_at=now, **values)
    await session.execute(
        dev.on_conflict_do_update(
            index_elements=[Device.id], set_={"last_seen_at": now, **values}
        )
    )
    run = pg_insert(SyncRun).values(
        id=sync_id, device_id=device_id, token_id=token_id, started_at=now, last_activity_at=now
    )
    await session.execute(
        run.on_conflict_do_update(index_elements=[SyncRun.id], set_={"last_activity_at": now})
    )


async def _bump(session: AsyncSession, sync_id: uuid.UUID, **deltas: int) -> None:
    await session.execute(
        update(SyncRun)
        .where(SyncRun.id == sync_id)
        .values({k: getattr(SyncRun, k) + v for k, v in deltas.items()})
    )


def _reject(index: int, raw: Any, exc: ValidationError | None, model: type[BaseModel]) -> Rejection:
    hc_id = raw.get("hc_id") if isinstance(raw, dict) else None
    type_ = raw.get("type") if isinstance(raw, dict) else None
    if exc is None:
        try:
            model.model_validate(raw)
        except ValidationError as e:
            exc = e
    reason, detail = (
        describe_validation_error(exc) if exc else ("invalid_record", "item could not be parsed")
    )
    return Rejection(
        index=index,
        hc_id=hc_id if isinstance(hc_id, str) else None,
        type=type_ if isinstance(type_, str) else None,
        reason=reason,
        detail=detail,
    )


# --------------------------------------------------------------------------- records


def _record_values(
    rec: RecordIn, settings: Settings, device_id: uuid.UUID, sync_id: uuid.UUID
) -> tuple[dict[str, Any], list[tuple[datetime, float]]]:
    spec = rec.spec
    tz = settings.tz
    if spec.daily is DailyKind.SLEEP:
        end = rec.end_time or rec.start_time
        offset = rec.end_offset_s if rec.end_offset_s is not None else rec.start_offset_s
        ld = local_date(end, offset, tz)
    else:
        ld = local_date(rec.start_time, rec.start_offset_s, tz)

    samples: dict[datetime, float] = {}
    if spec.uses_samples:
        for s in rec.parsed.samples:  # type: ignore[attr-defined]
            samples[s.time.astimezone(UTC)] = s.value
        data = rec.parsed.model_dump(mode="json", exclude_none=True, exclude={"samples"})
        data["sample_count"] = len(samples)
    else:
        data = rec.parsed.model_dump(mode="json", exclude_none=True)

    device = rec.source.device.model_dump(exclude_none=True) if rec.source.device else None
    values = {
        "type": rec.type,
        "hc_id": rec.hc_id,
        "start_ts": rec.start_time,
        "end_ts": rec.end_time,
        "start_offset_s": rec.start_offset_s,
        "end_offset_s": rec.end_offset_s,
        "local_date": ld,
        "data": data,
        "source_package": rec.source.package,
        "source_device": device or None,
        "recording_method": rec.source.recording_method,
        "last_modified_ts": rec.last_modified,
        "deleted_at": None,
        "device_id": device_id,
        "sync_id": sync_id,
        "updated_at": datetime.now(UTC),
    }
    return values, sorted(samples.items())


async def _sample_days(session: AsyncSession, record_ids: list[int]) -> set[TypeDay]:
    if not record_ids:
        return set()
    stmt = (
        select(HealthSample.type, HealthSample.local_date)
        .where(HealthSample.record_id.in_(record_ids))
        .distinct()
    )
    return {(t, d) for t, d in (await session.execute(stmt)).all()}


async def ingest_records(
    session: AsyncSession,
    settings: Settings,
    token_id: uuid.UUID,
    batch: RecordsBatch,
) -> RecordsResult:
    now = datetime.now(UTC)
    await _lock(session)
    await register_sync(
        session,
        token_id=token_id,
        device_id=batch.device_id,
        sync_id=batch.sync_id,
        meta=batch.device,
        now=now,
    )

    rejected: list[Rejection] = []
    # (type, hc_id) -> (record, built values, samples); highest last_modified wins in-batch.
    candidates: dict[tuple[str, str], RecordIn] = {}
    duplicates_in_batch = 0
    for index, item in enumerate(batch.records):
        if not isinstance(item, RecordIn):
            rejected.append(_reject(index, item, None, RecordIn))
            continue
        key = (item.type, item.hc_id)
        current = candidates.get(key)
        if current is None:
            candidates[key] = item
        else:
            duplicates_in_batch += 1
            if item.last_modified > current.last_modified:
                candidates[key] = item

    existing: dict[tuple[str, str], tuple[int, date, datetime]] = {}
    if candidates:
        stmt = select(
            HealthRecord.id,
            HealthRecord.type,
            HealthRecord.hc_id,
            HealthRecord.local_date,
            HealthRecord.last_modified_ts,
        ).where(tuple_(HealthRecord.type, HealthRecord.hc_id).in_(list(candidates)))
        existing = {(t, h): (i, d, lm) for i, t, h, d, lm in (await session.execute(stmt)).all()}

    touched: set[TypeDay] = set()
    to_insert: list[tuple[dict[str, Any], list[tuple[datetime, float]]]] = []
    to_update: list[tuple[int, dict[str, Any], list[tuple[datetime, float]]]] = []
    unchanged = duplicates_in_batch
    for key, rec in candidates.items():
        values, samples = _record_values(rec, settings, batch.device_id, batch.sync_id)
        found = existing.get(key)
        if found is None:
            to_insert.append((values, samples))
        elif rec.last_modified > found[2]:
            to_update.append((found[0], values, samples))
            touched.add((rec.type, found[1]))  # the day the record used to count for
        else:
            unchanged += 1
            continue
        touched.add((rec.type, values["local_date"]))

    sample_rows: list[dict[str, Any]] = []

    if to_insert:
        res = await session.execute(
            insert(HealthRecord).returning(HealthRecord.id, HealthRecord.type, HealthRecord.hc_id),
            [v for v, _ in to_insert],
        )
        ids = {(t, h): i for i, t, h in res.all()}
        for values, samples in to_insert:
            rid = ids[(values["type"], values["hc_id"])]
            sample_rows.extend(_sample_rows(rid, values, samples, settings, touched))

    if to_update:
        update_ids = [rid for rid, _, _ in to_update]
        touched |= await _sample_days(session, update_ids)
        await session.execute(delete(HealthSample).where(HealthSample.record_id.in_(update_ids)))
        await session.execute(
            update(HealthRecord), [{"id": rid, **values} for rid, values, _ in to_update]
        )
        for rid, values, samples in to_update:
            sample_rows.extend(_sample_rows(rid, values, samples, settings, touched))

    if sample_rows:
        await session.execute(insert(HealthSample), sample_rows)

    await recompute_days(session, touched, settings)

    inserted, updated = len(to_insert), len(to_update)
    await _bump(
        session,
        batch.sync_id,
        records_received=len(batch.records),
        records_inserted=inserted,
        records_updated=updated,
        records_unchanged=unchanged,
        records_rejected=len(rejected),
    )
    log.info(
        "ingest.records sync=%s received=%d inserted=%d updated=%d unchanged=%d rejected=%d days=%d",
        batch.sync_id, len(batch.records), inserted, updated, unchanged, len(rejected), len(touched),
    )
    return RecordsResult(
        received=len(batch.records),
        inserted=inserted,
        updated=updated,
        upserted=inserted + updated,
        unchanged=unchanged,
        rejected=rejected,
    )


def _sample_rows(
    record_id: int,
    values: dict[str, Any],
    samples: list[tuple[datetime, float]],
    settings: Settings,
    touched: set[TypeDay],
) -> list[dict[str, Any]]:
    rows = []
    for ts, value in samples:
        ld = local_date(ts, values["start_offset_s"], settings.tz)
        touched.add((values["type"], ld))
        rows.append(
            {"record_id": record_id, "ts": ts, "type": values["type"], "value": value, "local_date": ld}
        )
    return rows


# --------------------------------------------------------------------------- deletions


async def ingest_deletions(
    session: AsyncSession,
    settings: Settings,
    token_id: uuid.UUID,
    batch: DeletionsBatch,
) -> DeletionsResult:
    now = datetime.now(UTC)
    await _lock(session)
    await register_sync(
        session,
        token_id=token_id,
        device_id=batch.device_id,
        sync_id=batch.sync_id,
        meta=batch.device,
        now=now,
    )

    rejected: list[Rejection] = []
    wanted: list[DeletionItem] = []
    for index, item in enumerate(batch.items):
        if isinstance(item, DeletionItem):
            wanted.append(item)
        else:
            rejected.append(_reject(index, item, None, DeletionItem))

    rows_by_hc: dict[str, list[tuple[int, str, date, datetime | None]]] = defaultdict(list)
    if wanted:
        stmt = select(
            HealthRecord.id,
            HealthRecord.hc_id,
            HealthRecord.type,
            HealthRecord.local_date,
            HealthRecord.deleted_at,
        ).where(HealthRecord.hc_id.in_({w.hc_id for w in wanted}))
        for rid, hc_id, type_, ld, deleted_at in (await session.execute(stmt)).all():
            rows_by_hc[hc_id].append((rid, type_, ld, deleted_at))

    deleted = already = not_found = 0
    to_delete: dict[int, TypeDay] = {}
    seen: set[tuple[str, str | None]] = set()
    for item in wanted:
        if (item.hc_id, item.type) in seen:
            already += 1
            continue
        seen.add((item.hc_id, item.type))
        matches = [
            m for m in rows_by_hc.get(item.hc_id, []) if item.type is None or m[1] == item.type
        ]
        if not matches:
            not_found += 1
            continue
        live = [m for m in matches if m[3] is None]
        if not live:
            already += 1
            continue
        deleted += 1
        for rid, type_, ld, _ in live:
            to_delete[rid] = (type_, ld)

    touched: set[TypeDay] = set(to_delete.values())
    if to_delete:
        ids = list(to_delete)
        touched |= await _sample_days(session, ids)
        await session.execute(delete(HealthSample).where(HealthSample.record_id.in_(ids)))
        await session.execute(
            update(HealthRecord)
            .where(HealthRecord.id.in_(ids), HealthRecord.deleted_at.is_(None))
            .values(deleted_at=now, updated_at=now)
        )
        await recompute_days(session, touched, settings)

    await _bump(
        session,
        batch.sync_id,
        deletions_applied=deleted,
        deletions_not_found=not_found,
        records_rejected=len(rejected),
    )
    log.info(
        "ingest.deletions sync=%s received=%d deleted=%d already=%d not_found=%d rejected=%d",
        batch.sync_id, len(batch.items), deleted, already, not_found, len(rejected),
    )
    return DeletionsResult(
        received=len(batch.items),
        deleted=deleted,
        already_deleted=already,
        not_found=not_found,
        rejected=rejected,
    )


# --------------------------------------------------------------------------- daily aggregates


def _official_unit(type_: str) -> str | None:
    spec = SPECS[type_]
    return "s" if spec.daily in (DailyKind.SLEEP, DailyKind.SESSION) else spec.unit


async def ingest_daily_aggregates(
    session: AsyncSession,
    settings: Settings,
    token_id: uuid.UUID,
    batch: DailyAggregatesBatch,
) -> DailyAggregatesResult:
    now = datetime.now(UTC)
    await _lock(session)
    await register_sync(
        session,
        token_id=token_id,
        device_id=batch.device_id,
        sync_id=batch.sync_id,
        meta=batch.device,
        now=now,
    )

    rejected: list[Rejection] = []
    latest: dict[tuple[date, str], DailyAggregateItem] = {}
    superseded = 0
    for index, item in enumerate(batch.items):
        if not isinstance(item, DailyAggregateItem):
            rejected.append(_reject(index, item, None, DailyAggregateItem))
            continue
        key = (item.date, item.type)
        current = latest.get(key)
        if current is None:
            latest[key] = item
        else:
            superseded += 1
            if (item.snapshot_at or now) >= (current.snapshot_at or now):
                latest[key] = item

    stored: dict[tuple[date, str], tuple[Any, ...]] = {}
    if latest:
        stmt = select(
            DailyMetric.local_date,
            DailyMetric.type,
            DailyMetric.sum_value,
            DailyMetric.avg_value,
            DailyMetric.min_value,
            DailyMetric.max_value,
            DailyMetric.count,
            DailyMetric.detail,
            DailyMetric.snapshot_at,
        ).where(
            DailyMetric.source == "hc_official",
            tuple_(DailyMetric.local_date, DailyMetric.type).in_(list(latest)),
        )
        for ld, t, *rest in (await session.execute(stmt)).all():
            stored[(ld, t)] = tuple(rest)

    rows: list[dict[str, Any]] = []
    unchanged = superseded
    for (ld, type_), item in latest.items():
        snapshot = item.snapshot_at or now
        detail = {"data_origins": item.data_origins} if item.data_origins else None
        values = (item.sum, item.avg, item.min, item.max, item.count)
        prev = stored.get((ld, type_))
        # prev = (sum, avg, min, max, count, detail, snapshot_at)
        if prev is not None and (snapshot < prev[6] or (*values, detail) == tuple(prev[:6])):
            unchanged += 1
            continue
        rows.append(
            {
                "local_date": ld,
                "type": type_,
                "source": "hc_official",
                "sum_value": item.sum,
                "avg_value": item.avg,
                "min_value": item.min,
                "max_value": item.max,
                "count": item.count,
                "unit": _official_unit(type_),
                "detail": detail,
                "snapshot_at": snapshot,
                "updated_at": now,
            }
        )
    if rows:
        stmt2 = pg_insert(DailyMetric).values(rows)
        await session.execute(
            stmt2.on_conflict_do_update(
                index_elements=["local_date", "type", "source"],
                set_={
                    c: stmt2.excluded[c]
                    for c in (
                        "sum_value", "avg_value", "min_value", "max_value", "count", "unit",
                        "detail", "snapshot_at", "updated_at",
                    )
                },
            )
        )

    await _bump(
        session, batch.sync_id, aggregates_upserted=len(rows), records_rejected=len(rejected)
    )
    log.info(
        "ingest.aggregates sync=%s received=%d upserted=%d unchanged=%d rejected=%d",
        batch.sync_id, len(batch.items), len(rows), unchanged, len(rejected),
    )
    return DailyAggregatesResult(
        received=len(batch.items), upserted=len(rows), unchanged=unchanged, rejected=rejected
    )


# --------------------------------------------------------------------------- sync report


async def ingest_sync_report(
    session: AsyncSession, token_id: uuid.UUID, report: SyncReport
) -> None:
    now = datetime.now(UTC)
    await _lock(session)
    await register_sync(
        session,
        token_id=token_id,
        device_id=report.device_id,
        sync_id=report.sync_id,
        meta=report.device,
        now=now,
    )
    await session.execute(
        update(SyncRun)
        .where(SyncRun.id == report.sync_id)
        .values(
            mode=report.mode,
            status=report.status,
            started_at=report.started_at,
            finished_at=report.finished_at or now,
            last_activity_at=now,
            reported_counts=report.counts,
            errors=[e.model_dump(exclude_none=True) for e in report.errors] or None,
        )
    )
    log.info("ingest.sync_report sync=%s status=%s mode=%s", report.sync_id, report.status, report.mode)

"""SQLAlchemy models. The Alembic migration is the schema of record (a test checks they agree)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Double,
    ForeignKey,
    Identity,
    Index,
    Integer,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

TZ = DateTime(timezone=True)
NOW = func.now()


class Base(DeclarativeBase):
    pass


class Device(Base):
    __tablename__ = "device"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(100))
    model: Mapped[str | None] = mapped_column(String(100))
    app_version: Mapped[str | None] = mapped_column(String(100))
    first_seen_at: Mapped[datetime] = mapped_column(TZ, server_default=NOW)
    last_seen_at: Mapped[datetime] = mapped_column(TZ, server_default=NOW)


class IngestToken(Base):
    __tablename__ = "ingest_token"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100))
    # SHA-256 hex of the token. Tokens are 256-bit random, so a fast hash is appropriate.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    token_prefix: Mapped[str] = mapped_column(String(12))  # display only, e.g. "sbh_a1b2"
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=NOW)
    last_used_at: Mapped[datetime | None] = mapped_column(TZ)
    revoked_at: Mapped[datetime | None] = mapped_column(TZ)


class AdminUser(Base):
    __tablename__ = "admin_user"

    id: Mapped[int] = mapped_column(SmallInteger, Identity(), primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)  # Argon2id (PHC string)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=NOW)
    password_changed_at: Mapped[datetime] = mapped_column(TZ, server_default=NOW)


class UserSession(Base):
    __tablename__ = "user_session"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[int] = mapped_column(ForeignKey("admin_user.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=NOW)
    expires_at: Mapped[datetime] = mapped_column(TZ)
    last_seen_at: Mapped[datetime] = mapped_column(TZ, server_default=NOW)
    revoked_at: Mapped[datetime | None] = mapped_column(TZ)
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))

    __table_args__ = (Index("ix_user_session_expires_at", "expires_at"),)


class SyncRun(Base):
    __tablename__ = "sync_run"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)  # = client sync_id
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("device.id", ondelete="CASCADE"))
    token_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ingest_token.id", ondelete="SET NULL")
    )
    mode: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), server_default="running")
    started_at: Mapped[datetime] = mapped_column(TZ, server_default=NOW)
    finished_at: Mapped[datetime | None] = mapped_column(TZ)
    last_activity_at: Mapped[datetime] = mapped_column(TZ, server_default=NOW)
    # Counters as seen by the server (retries count again).
    records_received: Mapped[int] = mapped_column(Integer, server_default="0")
    records_inserted: Mapped[int] = mapped_column(Integer, server_default="0")
    records_updated: Mapped[int] = mapped_column(Integer, server_default="0")
    records_unchanged: Mapped[int] = mapped_column(Integer, server_default="0")
    records_rejected: Mapped[int] = mapped_column(Integer, server_default="0")
    deletions_applied: Mapped[int] = mapped_column(Integer, server_default="0")
    deletions_not_found: Mapped[int] = mapped_column(Integer, server_default="0")
    aggregates_upserted: Mapped[int] = mapped_column(Integer, server_default="0")
    # What the Reader reported in /ingest/sync-report.
    reported_counts: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    errors: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)

    __table_args__ = (
        CheckConstraint(
            "status IN ('running','completed','partial','failed')", name="ck_sync_run_status"
        ),
        Index("ix_sync_run_device_started", "device_id", "started_at"),
    )


class HealthRecord(Base):
    __tablename__ = "health_record"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    type: Mapped[str] = mapped_column(String(64))
    hc_id: Mapped[str] = mapped_column(String(128))
    start_ts: Mapped[datetime] = mapped_column(TZ)
    end_ts: Mapped[datetime | None] = mapped_column(TZ)
    start_offset_s: Mapped[int | None] = mapped_column(Integer)
    end_offset_s: Mapped[int | None] = mapped_column(Integer)
    # Local calendar day the record counts for (record offset, else Europe/Rome; sleep: wake day).
    local_date: Mapped[date] = mapped_column(Date)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    source_package: Mapped[str] = mapped_column(String(255))
    source_device: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    recording_method: Mapped[str] = mapped_column(String(16), server_default="unknown")
    last_modified_ts: Mapped[datetime] = mapped_column(TZ)
    ingested_at: Mapped[datetime] = mapped_column(TZ, server_default=NOW)
    updated_at: Mapped[datetime] = mapped_column(TZ, server_default=NOW)
    deleted_at: Mapped[datetime | None] = mapped_column(TZ)
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("device.id", ondelete="SET NULL")
    )
    sync_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    __table_args__ = (
        UniqueConstraint("type", "hc_id", name="uq_health_record_type_hc_id"),
        Index(
            "ix_health_record_type_start_live",
            "type",
            "start_ts",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_health_record_type_local_date_live",
            "type",
            "local_date",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_health_record_hc_id", "hc_id"),
    )


class HealthSample(Base):
    __tablename__ = "health_sample"

    record_id: Mapped[int] = mapped_column(
        ForeignKey("health_record.id", ondelete="CASCADE"), nullable=False
    )
    ts: Mapped[datetime] = mapped_column(TZ)
    type: Mapped[str] = mapped_column(String(64))
    value: Mapped[float] = mapped_column(Double)
    local_date: Mapped[date] = mapped_column(Date)

    __table_args__ = (
        PrimaryKeyConstraint("record_id", "ts", name="pk_health_sample"),
        Index("ix_health_sample_type_ts", "type", "ts"),
        Index("ix_health_sample_type_local_date", "type", "local_date"),
    )


class DailyMetric(Base):
    __tablename__ = "daily_metric"

    local_date: Mapped[date] = mapped_column(Date)
    type: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(16))  # 'hc_official' | 'computed'
    sum_value: Mapped[float | None] = mapped_column(Double)
    avg_value: Mapped[float | None] = mapped_column(Double)
    min_value: Mapped[float | None] = mapped_column(Double)
    max_value: Mapped[float | None] = mapped_column(Double)
    count: Mapped[int | None] = mapped_column(Integer)
    unit: Mapped[str | None] = mapped_column(String(32))
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    snapshot_at: Mapped[datetime] = mapped_column(TZ, server_default=NOW)  # official: Reader's
    updated_at: Mapped[datetime] = mapped_column(TZ, server_default=NOW)

    __table_args__ = (
        PrimaryKeyConstraint("local_date", "type", "source", name="pk_daily_metric"),
        CheckConstraint("source IN ('hc_official','computed')", name="ck_daily_metric_source"),
        Index("ix_daily_metric_type_date", "type", "local_date"),
    )

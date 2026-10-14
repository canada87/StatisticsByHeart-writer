"""Initial schema: records, samples, daily metrics, devices, tokens, sync runs, admin sessions.

Revision ID: 0001
Revises:
Create Date: 2026-10-14
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "device",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(100)),
        sa.Column("model", sa.String(100)),
        sa.Column("app_version", sa.String(100)),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    )

    op.create_table(
        "ingest_token",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("token_prefix", sa.String(12), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "admin_user",
        sa.Column("id", sa.SmallInteger, sa.Identity(), primary_key=True),
        sa.Column("username", sa.String(100), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column(
            "password_changed_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False
        ),
    )

    op.create_table(
        "user_session",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.SmallInteger,
            sa.ForeignKey("admin_user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("ip", sa.String(64)),
        sa.Column("user_agent", sa.String(300)),
    )
    op.create_index("ix_user_session_expires_at", "user_session", ["expires_at"])

    op.create_table(
        "sync_run",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "device_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("device.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "token_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ingest_token.id", ondelete="SET NULL"),
        ),
        sa.Column("mode", sa.String(16)),
        sa.Column("status", sa.String(16), server_default="running", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column(
            "last_activity_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False
        ),
        sa.Column("records_received", sa.Integer, server_default="0", nullable=False),
        sa.Column("records_inserted", sa.Integer, server_default="0", nullable=False),
        sa.Column("records_updated", sa.Integer, server_default="0", nullable=False),
        sa.Column("records_unchanged", sa.Integer, server_default="0", nullable=False),
        sa.Column("records_rejected", sa.Integer, server_default="0", nullable=False),
        sa.Column("deletions_applied", sa.Integer, server_default="0", nullable=False),
        sa.Column("deletions_not_found", sa.Integer, server_default="0", nullable=False),
        sa.Column("aggregates_upserted", sa.Integer, server_default="0", nullable=False),
        sa.Column("reported_counts", postgresql.JSONB),
        sa.Column("errors", postgresql.JSONB),
        sa.CheckConstraint(
            "status IN ('running','completed','partial','failed')", name="ck_sync_run_status"
        ),
    )
    op.create_index("ix_sync_run_device_started", "sync_run", ["device_id", "started_at"])

    op.create_table(
        "health_record",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("hc_id", sa.String(128), nullable=False),
        sa.Column("start_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_ts", sa.DateTime(timezone=True)),
        sa.Column("start_offset_s", sa.Integer),
        sa.Column("end_offset_s", sa.Integer),
        sa.Column("local_date", sa.Date, nullable=False),
        sa.Column(
            "data", postgresql.JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("source_package", sa.String(255), nullable=False),
        sa.Column("source_device", postgresql.JSONB),
        sa.Column("recording_method", sa.String(16), server_default="unknown", nullable=False),
        sa.Column("last_modified_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column(
            "device_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("device.id", ondelete="SET NULL"),
        ),
        sa.Column("sync_id", postgresql.UUID(as_uuid=True)),
        sa.UniqueConstraint("type", "hc_id", name="uq_health_record_type_hc_id"),
    )
    op.create_index(
        "ix_health_record_type_start_live",
        "health_record",
        ["type", "start_ts"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_health_record_type_local_date_live",
        "health_record",
        ["type", "local_date"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index("ix_health_record_hc_id", "health_record", ["hc_id"])

    op.create_table(
        "health_sample",
        sa.Column(
            "record_id",
            sa.BigInteger,
            sa.ForeignKey("health_record.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("value", sa.Double, nullable=False),
        sa.Column("local_date", sa.Date, nullable=False),
        sa.PrimaryKeyConstraint("record_id", "ts", name="pk_health_sample"),
    )
    op.create_index("ix_health_sample_type_ts", "health_sample", ["type", "ts"])
    op.create_index("ix_health_sample_type_local_date", "health_sample", ["type", "local_date"])

    op.create_table(
        "daily_metric",
        sa.Column("local_date", sa.Date, nullable=False),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("sum_value", sa.Double),
        sa.Column("avg_value", sa.Double),
        sa.Column("min_value", sa.Double),
        sa.Column("max_value", sa.Double),
        sa.Column("count", sa.Integer),
        sa.Column("unit", sa.String(32)),
        sa.Column("detail", postgresql.JSONB),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("local_date", "type", "source", name="pk_daily_metric"),
        sa.CheckConstraint("source IN ('hc_official','computed')", name="ck_daily_metric_source"),
    )
    op.create_index("ix_daily_metric_type_date", "daily_metric", ["type", "local_date"])


def downgrade() -> None:
    for table in (
        "daily_metric",
        "health_sample",
        "health_record",
        "sync_run",
        "user_session",
        "admin_user",
        "ingest_token",
        "device",
    ):
        op.drop_table(table)

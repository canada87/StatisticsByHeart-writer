"""record_exclusion: measures the user excluded from every analysis (reversible, survives sync).

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-31
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "record_exclusion",
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("hc_id", sa.String(128), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason", sa.String(200)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("type", "hc_id", name="pk_record_exclusion"),
    )
    op.create_index("ix_record_exclusion_group", "record_exclusion", ["group_id"])


def downgrade() -> None:
    op.drop_index("ix_record_exclusion_group", table_name="record_exclusion")
    op.drop_table("record_exclusion")

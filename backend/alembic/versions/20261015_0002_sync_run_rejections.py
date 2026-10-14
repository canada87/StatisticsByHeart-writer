"""sync_run.rejections: per (type, reason) tally of records the writer refused.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-15
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sync_run", sa.Column("rejections", postgresql.JSONB))


def downgrade() -> None:
    op.drop_column("sync_run", "rejections")

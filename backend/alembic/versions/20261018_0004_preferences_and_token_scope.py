"""user_preference (server-side UI preferences) and ingest_token.scope (ingest | ha).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-18
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_preference",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    # existing tokens are all ingest tokens
    op.add_column(
        "ingest_token",
        sa.Column("scope", sa.String(16), nullable=False, server_default="ingest"),
    )
    op.create_check_constraint("ck_ingest_token_scope", "ingest_token", "scope IN ('ingest','ha')")


def downgrade() -> None:
    op.drop_constraint("ck_ingest_token_scope", "ingest_token", type_="check")
    op.drop_column("ingest_token", "scope")
    op.drop_table("user_preference")

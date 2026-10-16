"""exercise_override: the user's manual "real workout" verdict per Health Connect record.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-16
"""

import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "exercise_override",
        sa.Column("hc_id", sa.String(128), primary_key=True),
        sa.Column("is_real", sa.Boolean(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("exercise_override")

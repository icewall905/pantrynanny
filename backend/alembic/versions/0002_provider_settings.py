"""provider settings (admin overrides for lookup providers)

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-19 14:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provider_settings",
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=True),
        sa.Column("api_key", sa.Text(), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("name", name="pk_provider_settings"),
    )
    op.create_index("ix_lookup_attempts_code", "lookup_attempts", ["code"])
    op.create_index("ix_lookup_attempts_status", "lookup_attempts", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_lookup_attempts_status", table_name="lookup_attempts")
    op.drop_index("ix_lookup_attempts_code", table_name="lookup_attempts")
    op.drop_table("provider_settings")

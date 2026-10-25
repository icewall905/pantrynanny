"""recipes for machine clients: household staples, recipe course, scan defaults, read-only tokens

- household_settings.staples: the "always in the house" list (NULL = built-in defaults)
- recipes.course (breakfast/lunch/dinner/...) and recipes.source_checked_at (resumable backfill)
- categories.default_expiry_days / default_location_id: one-tap expiry and location after a scan
- sessions.scope: "full" or "read" (a read-only device token)

Revision ID: 0011
Revises: 0010
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("household_settings", sa.Column("staples", postgresql.ARRAY(sa.Text())))
    op.add_column("recipes", sa.Column("course", sa.String(16)))
    op.add_column("recipes", sa.Column("source_checked_at", sa.DateTime(timezone=True)))
    op.add_column("categories", sa.Column("default_expiry_days", sa.Integer()))
    op.add_column(
        "categories",
        sa.Column(
            "default_location_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("locations.id", ondelete="SET NULL"),
        ),
    )
    op.add_column(
        "sessions", sa.Column("scope", sa.String(8), server_default="full", nullable=False)
    )


def downgrade() -> None:
    op.drop_column("sessions", "scope")
    op.drop_column("categories", "default_location_id")
    op.drop_column("categories", "default_expiry_days")
    op.drop_column("recipes", "source_checked_at")
    op.drop_column("recipes", "course")
    op.drop_column("household_settings", "staples")

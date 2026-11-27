"""recipe categories and an external id (re-runnable imports, e.g. from Mealie)

- recipes.categories: free-form categories ("Dinner", "School Lunch"), separate from tags
- recipes.external_id: where an imported recipe came from ("mealie:<uuid>"), unique per household

Revision ID: 0012
Revises: 0011
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "recipes",
        sa.Column(
            "categories",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
    )
    op.add_column("recipes", sa.Column("external_id", sa.Text()))
    op.create_index(
        "ux_recipes_household_external",
        "recipes",
        ["household_id", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ux_recipes_household_external", table_name="recipes")
    op.drop_column("recipes", "external_id")
    op.drop_column("recipes", "categories")

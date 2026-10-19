"""global seed catalogue of retail barcodes (open data, imported by pantrynanny-admin import-seed)

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "catalogue_seed",
        sa.Column("code", sa.String(length=14), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("brand", sa.Text(), nullable=True),
        sa.Column("package_size", sa.Numeric(12, 3), nullable=True),
        sa.Column("package_unit", sa.String(length=8), nullable=True),
        sa.Column("category_hint", sa.Text(), nullable=True),
        sa.Column("allergens", ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("countries", ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("license", sa.Text(), nullable=False),
        sa.Column("dataset_version", sa.String(length=64), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("code", name="pk_catalogue_seed"),
    )


def downgrade() -> None:
    op.drop_table("catalogue_seed")

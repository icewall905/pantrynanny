"""optional shop per shopping-list item (additive)

Revision ID: 0008
Revises: 0007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("shopping_items", sa.Column("store", sa.String(60), nullable=True))


def downgrade() -> None:
    op.drop_column("shopping_items", "store")

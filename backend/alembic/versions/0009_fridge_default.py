"""unknown items go to the fridge: make "Køleskab" the household default location

Only households that still have the original seed default ("Spisekammer") and a live
"Køleskab" are changed; a default the household picked itself is left alone. Data only.

Revision ID: 0009
Revises: 0008
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Two steps: the one-default-per-household index is checked row by row.
PICK = """
CREATE TEMP TABLE pn_fridge_swap ON COMMIT DROP AS
SELECT p.id AS pantry, f.id AS fridge
FROM locations p
JOIN locations f ON f.household_id = p.household_id
     AND f.name = 'Køleskab' AND f.deleted_at IS NULL
WHERE p.is_default AND p.name = 'Spisekammer' AND p.deleted_at IS NULL
"""


def upgrade() -> None:
    op.execute(PICK)
    op.execute(
        "UPDATE locations SET is_default = false WHERE id IN (SELECT pantry FROM pn_fridge_swap)"
    )
    op.execute(
        "UPDATE locations SET is_default = true WHERE id IN (SELECT fridge FROM pn_fridge_swap)"
    )
    op.execute("DROP TABLE pn_fridge_swap")


def downgrade() -> None:
    # Data-only change; the previous default cannot be told apart from a later choice.
    pass

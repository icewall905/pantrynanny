"""stamp the writing transaction id next to change_seq (provably complete sync cursors)

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("products", "stock_batches", "locations", "categories")

STAMP_FN = """
CREATE OR REPLACE FUNCTION pn_stamp_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.change_seq := nextval('change_seq_seq');
    NEW.change_xid := pg_current_xact_id()::text::bigint;
    IF TG_OP = 'UPDATE' THEN
        NEW.updated_at := clock_timestamp();
    END IF;
    RETURN NEW;
END
$$
"""

OLD_STAMP_FN = """
CREATE OR REPLACE FUNCTION pn_stamp_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.change_seq := nextval('change_seq_seq');
    IF TG_OP = 'UPDATE' THEN
        NEW.updated_at := clock_timestamp();
    END IF;
    RETURN NEW;
END
$$
"""


def upgrade() -> None:
    for t in TABLES:
        op.execute(f"ALTER TABLE {t} ADD COLUMN change_xid bigint NOT NULL DEFAULT 0")
        op.execute(f"CREATE INDEX ix_{t}_change_xid ON {t} (change_xid)")
        op.execute(f"CREATE INDEX ix_{t}_change_seq ON {t} (change_seq)")
    op.execute(STAMP_FN)


def downgrade() -> None:
    op.execute(OLD_STAMP_FN)
    for t in TABLES:
        op.execute(f"DROP INDEX ix_{t}_change_seq")
        op.execute(f"DROP INDEX ix_{t}_change_xid")
        op.execute(f"ALTER TABLE {t} DROP COLUMN change_xid")

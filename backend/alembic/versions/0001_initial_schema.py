"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-19 11:31:36.654760
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


UNACCENT_FN = """
CREATE FUNCTION pn_unaccent(text) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
AS $$ SELECT public.unaccent('public.unaccent'::regdictionary, $1) $$
"""

STAMP_FN = """
CREATE FUNCTION pn_stamp_change() RETURNS trigger
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

STAMPED_TABLES = ("products", "stock_batches", "locations", "categories")

TRIGRAM_INDEXES = (
    ("ix_products_name_trgm", "products", "pn_unaccent(lower(name))"),
    ("ix_products_brand_trgm", "products", "pn_unaccent(lower(coalesce(brand, '')))"),
    ("ix_product_aliases_alias_trgm", "product_aliases", "pn_unaccent(lower(alias))"),
    ("ix_categories_name_trgm", "categories", "pn_unaccent(lower(name))"),
    ("ix_product_barcodes_raw_pattern", "product_barcodes", "raw text_pattern_ops"),
    ("ix_product_barcodes_code_pattern", "product_barcodes", "code text_pattern_ops"),
)


def upgrade() -> None:
    # Extensions, sequence and immutable unaccent wrapper must exist before the tables.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
    op.execute("CREATE SEQUENCE change_seq_seq")
    op.execute(UNACCENT_FN)
    op.create_table(
        "households",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_households")),
    )
    op.create_table(
        "lookup_cache",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("retry_after", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lookup_cache")),
        sa.UniqueConstraint("code", "provider", name="uq_lookup_cache_code_provider"),
    )
    op.create_table(
        "categories",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("household_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("icon", sa.Text(), nullable=True),
        sa.Column("color", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("change_seq", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["households.id"],
            name=op.f("fk_categories_household_id_households"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_categories")),
    )
    op.create_index("ix_categories_household", "categories", ["household_id"], unique=False)
    op.create_table(
        "household_settings",
        sa.Column("household_id", sa.UUID(), nullable=False),
        sa.Column("locale", sa.String(length=8), server_default="da", nullable=False),
        sa.Column(
            "allow_negative_stock", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("expiry_soon_days", sa.Integer(), server_default=sa.text("3"), nullable=False),
        sa.Column(
            "auto_shopping_low_stock", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "remove_mode_timeout_min", sa.Integer(), server_default=sa.text("10"), nullable=False
        ),
        sa.Column("scan_rearm_ms", sa.Integer(), server_default=sa.text("600"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["households.id"],
            name=op.f("fk_household_settings_household_id_households"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("household_id", name=op.f("pk_household_settings")),
    )
    op.create_table(
        "locations",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("household_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("icon", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("change_seq", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["households.id"],
            name=op.f("fk_locations_household_id_households"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_locations")),
    )
    op.create_index("ix_locations_household", "locations", ["household_id"], unique=False)
    op.create_index(
        "uq_locations_default",
        "locations",
        ["household_id"],
        unique=True,
        postgresql_where=sa.text("is_default AND deleted_at IS NULL"),
    )
    op.create_table(
        "lookup_attempts",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("household_id", sa.UUID(), nullable=True),
        sa.Column("product_id", sa.UUID(), nullable=True),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["households.id"],
            name=op.f("fk_lookup_attempts_household_id_households"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lookup_attempts")),
    )
    op.create_index("ix_lookup_attempts_created", "lookup_attempts", ["created_at"], unique=False)
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("household_id", sa.UUID(), nullable=False),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["households.id"],
            name=op.f("fk_users_household_id_households"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("username", name=op.f("uq_users_username")),
    )
    op.create_table(
        "kiosk_codes",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("household_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_kiosk_codes_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["households.id"],
            name=op.f("fk_kiosk_codes_household_id_households"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kiosk_codes")),
        sa.UniqueConstraint("code_hash", name=op.f("uq_kiosk_codes_code_hash")),
    )
    op.create_table(
        "products",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("household_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("brand", sa.Text(), nullable=True),
        sa.Column("category_id", sa.UUID(), nullable=True),
        sa.Column("default_location_id", sa.UUID(), nullable=True),
        sa.Column("image_path", sa.Text(), nullable=True),
        sa.Column("package_size", sa.Numeric(precision=12, scale=3), nullable=True),
        sa.Column("package_unit", sa.String(length=8), nullable=True),
        sa.Column("stock_unit", sa.String(length=8), server_default="pcs", nullable=False),
        sa.Column("min_stock", sa.Numeric(precision=12, scale=3), nullable=True),
        sa.Column("ingredients", sa.Text(), nullable=True),
        sa.Column(
            "allergens", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column("nutrition", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "countries", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column("status", sa.String(length=16), server_default="known", nullable=False),
        sa.Column("source", sa.String(length=32), server_default="user", nullable=False),
        sa.Column("source_attribution", sa.Text(), nullable=True),
        sa.Column("lookup_confidence", sa.Float(), nullable=True),
        sa.Column(
            "locked_fields",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("merged_into_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("change_seq", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name=op.f("fk_products_category_id_categories"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["default_location_id"],
            ["locations.id"],
            name=op.f("fk_products_default_location_id_locations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["households.id"],
            name=op.f("fk_products_household_id_households"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_products")),
    )
    op.create_index(
        "ix_products_household_category", "products", ["household_id", "category_id"], unique=False
    )
    op.create_index(
        "ix_products_household_status", "products", ["household_id", "status"], unique=False
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("household_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("device_name", sa.Text(), nullable=True),
        sa.Column("platform", sa.Text(), nullable=True),
        sa.Column("ttl_seconds", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_used_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["households.id"],
            name=op.f("fk_sessions_household_id_households"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_sessions_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_sessions_token_hash")),
    )
    op.create_table(
        "enrichment_queue",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("household_id", sa.UUID(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["households.id"],
            name=op.f("fk_enrichment_queue_household_id_households"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_enrichment_queue_product_id_products"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_enrichment_queue")),
        sa.UniqueConstraint("product_id", "code", name="uq_enrichment_queue_product_code"),
    )
    op.create_index(
        "ix_enrichment_queue_due", "enrichment_queue", ["status", "next_attempt_at"], unique=False
    )
    op.create_table(
        "product_aliases",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("household_id", sa.UUID(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("alias", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["households.id"],
            name=op.f("fk_product_aliases_household_id_households"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_product_aliases_product_id_products"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_aliases")),
        sa.UniqueConstraint("product_id", "alias", name="uq_product_aliases_product_alias"),
    )
    op.create_table(
        "product_barcodes",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("household_id", sa.UUID(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("raw", sa.Text(), nullable=False),
        sa.Column("symbology", sa.String(length=16), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["households.id"],
            name=op.f("fk_product_barcodes_household_id_households"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_product_barcodes_product_id_products"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_barcodes")),
        sa.UniqueConstraint("household_id", "code", name="uq_product_barcodes_household_code"),
    )
    op.create_index("ix_product_barcodes_product", "product_barcodes", ["product_id"], unique=False)
    op.create_table(
        "shopping_items",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("household_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("unit", sa.String(length=8), nullable=True),
        sa.Column("category_id", sa.UUID(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("checked", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(length=16), server_default="manual", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name=op.f("fk_shopping_items_category_id_categories"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["households.id"],
            name=op.f("fk_shopping_items_household_id_households"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_shopping_items_product_id_products"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shopping_items")),
    )
    op.create_index("ix_shopping_household", "shopping_items", ["household_id"], unique=False)
    op.create_index(
        "uq_shopping_open_product",
        "shopping_items",
        ["household_id", "product_id"],
        unique=True,
        postgresql_where=sa.text(
            "checked = false AND product_id IS NOT NULL AND deleted_at IS NULL"
        ),
    )
    op.create_table(
        "stock_batches",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("household_id", sa.UUID(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("location_id", sa.UUID(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("expires_at", sa.Date(), nullable=True),
        sa.Column("opened_at", sa.Date(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("change_seq", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["households.id"],
            name=op.f("fk_stock_batches_household_id_households"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["location_id"], ["locations.id"], name=op.f("fk_stock_batches_location_id_locations")
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_stock_batches_product_id_products"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stock_batches")),
    )
    op.create_index(
        "ix_stock_batches_expires", "stock_batches", ["household_id", "expires_at"], unique=False
    )
    op.create_index(
        "ix_stock_batches_location", "stock_batches", ["household_id", "location_id"], unique=False
    )
    op.create_index(
        "ix_stock_batches_product", "stock_batches", ["household_id", "product_id"], unique=False
    )
    op.create_table(
        "stock_transactions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("household_id", sa.UUID(), nullable=False),
        sa.Column("client_op_id", sa.UUID(), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("quantity_delta", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("batch_id", sa.UUID(), nullable=True),
        sa.Column("location_id", sa.UUID(), nullable=True),
        sa.Column("to_location_id", sa.UUID(), nullable=True),
        sa.Column("undoes_id", sa.UUID(), nullable=True),
        sa.Column("undone", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("session_id", sa.UUID(), nullable=True),
        sa.Column("device_name", sa.Text(), nullable=True),
        sa.Column("device_id", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("op_error", sa.Text(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["stock_batches.id"],
            name=op.f("fk_stock_transactions_batch_id_stock_batches"),
        ),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["households.id"],
            name=op.f("fk_stock_transactions_household_id_households"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["location_id"],
            ["locations.id"],
            name=op.f("fk_stock_transactions_location_id_locations"),
        ),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"], name=op.f("fk_stock_transactions_product_id_products")
        ),
        sa.ForeignKeyConstraint(
            ["to_location_id"],
            ["locations.id"],
            name=op.f("fk_stock_transactions_to_location_id_locations"),
        ),
        sa.ForeignKeyConstraint(
            ["undoes_id"],
            ["stock_transactions.id"],
            name=op.f("fk_stock_transactions_undoes_id_stock_transactions"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_stock_transactions_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stock_transactions")),
        sa.UniqueConstraint(
            "household_id", "client_op_id", name="uq_stock_transactions_household_client_op"
        ),
    )
    op.create_index(
        "ix_stock_transactions_created",
        "stock_transactions",
        ["household_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_stock_transactions_product",
        "stock_transactions",
        ["household_id", "product_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "stock_transaction_lines",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("transaction_id", sa.UUID(), nullable=False),
        sa.Column("batch_id", sa.UUID(), nullable=False),
        sa.Column("seq", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("delta", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["stock_batches.id"],
            name=op.f("fk_stock_transaction_lines_batch_id_stock_batches"),
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["stock_transactions.id"],
            name=op.f("fk_stock_transaction_lines_transaction_id_stock_transactions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stock_transaction_lines")),
    )
    op.create_index(
        "ix_stock_transaction_lines_txn",
        "stock_transaction_lines",
        ["transaction_id"],
        unique=False,
    )

    op.execute(STAMP_FN)
    for table in STAMPED_TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_stamp_change BEFORE INSERT OR UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION pn_stamp_change()"
        )
    for name, table, expr in TRIGRAM_INDEXES:
        if expr.endswith("text_pattern_ops"):
            op.execute(f"CREATE INDEX {name} ON {table} ({expr})")
        else:
            op.execute(f"CREATE INDEX {name} ON {table} USING gin (({expr}) gin_trgm_ops)")


def downgrade() -> None:
    op.drop_index("ix_stock_transaction_lines_txn", table_name="stock_transaction_lines")
    op.drop_table("stock_transaction_lines")
    op.drop_index("ix_stock_transactions_product", table_name="stock_transactions")
    op.drop_index("ix_stock_transactions_created", table_name="stock_transactions")
    op.drop_table("stock_transactions")
    op.drop_index("ix_stock_batches_product", table_name="stock_batches")
    op.drop_index("ix_stock_batches_location", table_name="stock_batches")
    op.drop_index("ix_stock_batches_expires", table_name="stock_batches")
    op.drop_table("stock_batches")
    op.drop_index(
        "uq_shopping_open_product",
        table_name="shopping_items",
        postgresql_where=sa.text(
            "checked = false AND product_id IS NOT NULL AND deleted_at IS NULL"
        ),
    )
    op.drop_index("ix_shopping_household", table_name="shopping_items")
    op.drop_table("shopping_items")
    op.drop_index("ix_product_barcodes_product", table_name="product_barcodes")
    op.drop_table("product_barcodes")
    op.drop_table("product_aliases")
    op.drop_index("ix_enrichment_queue_due", table_name="enrichment_queue")
    op.drop_table("enrichment_queue")
    op.drop_table("sessions")
    op.drop_index("ix_products_household_status", table_name="products")
    op.drop_index("ix_products_household_category", table_name="products")
    op.drop_table("products")
    op.drop_table("kiosk_codes")
    op.drop_table("users")
    op.drop_index("ix_lookup_attempts_created", table_name="lookup_attempts")
    op.drop_table("lookup_attempts")
    op.drop_index(
        "uq_locations_default",
        table_name="locations",
        postgresql_where=sa.text("is_default AND deleted_at IS NULL"),
    )
    op.drop_index("ix_locations_household", table_name="locations")
    op.drop_table("locations")
    op.drop_table("household_settings")
    op.drop_index("ix_categories_household", table_name="categories")
    op.drop_table("categories")
    op.drop_table("lookup_cache")
    op.drop_table("households")
    op.execute("DROP FUNCTION pn_stamp_change()")
    op.execute("DROP FUNCTION pn_unaccent(text)")
    op.execute("DROP SEQUENCE change_seq_seq")

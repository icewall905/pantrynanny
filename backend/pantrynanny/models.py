"""SQLAlchemy models. The Alembic migration is the schema source of truth for triggers/indexes
that cannot be expressed here (change_seq stamping, trigram search indexes)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.schema import FetchedValue

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)
    __mapper_args__ = {"eager_defaults": True}


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )


def _ts(nullable: bool = False) -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=nullable)


def _fk(target: str, nullable: bool = False, ondelete: str | None = None):
    return mapped_column(
        UUID(as_uuid=True), ForeignKey(target, ondelete=ondelete), nullable=nullable
    )


def _updated() -> Mapped[datetime]:
    # Maintained by the pn_stamp_change trigger where present.
    return mapped_column(
        DateTime(timezone=True), server_default=func.now(), server_onupdate=FetchedValue()
    )


def _change_seq() -> Mapped[int]:
    return mapped_column(
        BigInteger, nullable=False, server_default=FetchedValue(), server_onupdate=FetchedValue()
    )


def _change_xid() -> Mapped[int]:
    # Transaction id of the writer, stamped by the trigger; drives the sync cursor.
    return mapped_column(
        BigInteger,
        nullable=False,
        server_default=text("0"),
        server_onupdate=FetchedValue(),
    )


class Household(Base):
    __tablename__ = "households"
    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _ts()


class HouseholdSettings(Base):
    __tablename__ = "household_settings"
    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("households.id", ondelete="CASCADE"), primary_key=True
    )
    locale: Mapped[str] = mapped_column(String(8), default="da", server_default="da")
    allow_negative_stock: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    expiry_soon_days: Mapped[int] = mapped_column(Integer, default=3, server_default=text("3"))
    auto_shopping_low_stock: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true")
    )
    remove_mode_timeout_min: Mapped[int] = mapped_column(
        Integer, default=10, server_default=text("10")
    )
    scan_rearm_ms: Mapped[int] = mapped_column(Integer, default=600, server_default=text("600"))
    updated_at: Mapped[datetime] = _ts()


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = _pk()
    household_id: Mapped[uuid.UUID] = _fk("households.id", ondelete="CASCADE")
    username: Mapped[str] = mapped_column(Text, unique=True)
    display_name: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(16))  # owner | admin | member
    password_hash: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _ts()


class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[uuid.UUID] = _pk()
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[uuid.UUID | None] = _fk("users.id", nullable=True, ondelete="CASCADE")
    household_id: Mapped[uuid.UUID] = _fk("households.id", ondelete="CASCADE")
    kind: Mapped[str] = mapped_column(String(16))  # browser | device | kiosk
    device_name: Mapped[str | None] = mapped_column(Text)
    platform: Mapped[str | None] = mapped_column(Text)
    ttl_seconds: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = _ts()
    last_used_at: Mapped[datetime] = _ts()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KioskCode(Base):
    __tablename__ = "kiosk_codes"
    id: Mapped[uuid.UUID] = _pk()
    household_id: Mapped[uuid.UUID] = _fk("households.id", ondelete="CASCADE")
    name: Mapped[str] = mapped_column(Text)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_by: Mapped[uuid.UUID | None] = _fk("users.id", nullable=True, ondelete="SET NULL")
    created_at: Mapped[datetime] = _ts()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Location(Base):
    __tablename__ = "locations"
    id: Mapped[uuid.UUID] = _pk()
    household_id: Mapped[uuid.UUID] = _fk("households.id", ondelete="CASCADE")
    name: Mapped[str] = mapped_column(Text)
    icon: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _updated()
    change_seq: Mapped[int] = _change_seq()
    change_xid: Mapped[int] = _change_xid()

    __table_args__ = (
        Index(
            "uq_locations_default",
            "household_id",
            unique=True,
            postgresql_where=text("is_default AND deleted_at IS NULL"),
        ),
        Index("ix_locations_household", "household_id"),
    )


class Category(Base):
    __tablename__ = "categories"
    id: Mapped[uuid.UUID] = _pk()
    household_id: Mapped[uuid.UUID] = _fk("households.id", ondelete="CASCADE")
    name: Mapped[str] = mapped_column(Text)
    icon: Mapped[str | None] = mapped_column(Text)
    color: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _updated()
    change_seq: Mapped[int] = _change_seq()
    change_xid: Mapped[int] = _change_xid()

    __table_args__ = (Index("ix_categories_household", "household_id"),)


class Product(Base):
    __tablename__ = "products"
    id: Mapped[uuid.UUID] = _pk()
    household_id: Mapped[uuid.UUID] = _fk("households.id", ondelete="CASCADE")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    name: Mapped[str] = mapped_column(Text)
    brand: Mapped[str | None] = mapped_column(Text)
    category_id: Mapped[uuid.UUID | None] = _fk("categories.id", nullable=True, ondelete="SET NULL")
    default_location_id: Mapped[uuid.UUID | None] = _fk(
        "locations.id", nullable=True, ondelete="SET NULL"
    )
    image_path: Mapped[str | None] = mapped_column(Text)
    package_size: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    package_unit: Mapped[str | None] = mapped_column(String(8))
    stock_unit: Mapped[str] = mapped_column(String(8), default="pcs", server_default="pcs")
    min_stock: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    ingredients: Mapped[str | None] = mapped_column(Text)
    allergens: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list, server_default=text("'{}'")
    )
    nutrition: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    description: Mapped[str | None] = mapped_column(Text)
    countries: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list, server_default=text("'{}'")
    )
    status: Mapped[str] = mapped_column(String(16), default="known", server_default="known")
    source: Mapped[str] = mapped_column(String(32), default="user", server_default="user")
    source_attribution: Mapped[str | None] = mapped_column(Text)
    lookup_confidence: Mapped[float | None] = mapped_column(Float)
    locked_fields: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list, server_default=text("'{}'")
    )
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _updated()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    change_seq: Mapped[int] = _change_seq()
    change_xid: Mapped[int] = _change_xid()

    barcodes: Mapped[list["ProductBarcode"]] = relationship(
        lazy="selectin", order_by="ProductBarcode.created_at", cascade="all, delete-orphan"
    )
    aliases: Mapped[list["ProductAlias"]] = relationship(
        lazy="selectin", order_by="ProductAlias.created_at", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_products_household_status", "household_id", "status"),
        Index("ix_products_household_category", "household_id", "category_id"),
    )


class ProductBarcode(Base):
    __tablename__ = "product_barcodes"
    id: Mapped[uuid.UUID] = _pk()
    household_id: Mapped[uuid.UUID] = _fk("households.id", ondelete="CASCADE")
    product_id: Mapped[uuid.UUID] = _fk("products.id", ondelete="CASCADE")
    code: Mapped[str] = mapped_column(Text)
    raw: Mapped[str] = mapped_column(Text)
    symbology: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = _ts()

    __table_args__ = (
        UniqueConstraint("household_id", "code", name="uq_product_barcodes_household_code"),
        Index("ix_product_barcodes_product", "product_id"),
    )


class ProductAlias(Base):
    __tablename__ = "product_aliases"
    id: Mapped[uuid.UUID] = _pk()
    household_id: Mapped[uuid.UUID] = _fk("households.id", ondelete="CASCADE")
    product_id: Mapped[uuid.UUID] = _fk("products.id", ondelete="CASCADE")
    alias: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _ts()

    __table_args__ = (
        UniqueConstraint("product_id", "alias", name="uq_product_aliases_product_alias"),
    )


class StockBatch(Base):
    __tablename__ = "stock_batches"
    id: Mapped[uuid.UUID] = _pk()
    household_id: Mapped[uuid.UUID] = _fk("households.id", ondelete="CASCADE")
    product_id: Mapped[uuid.UUID] = _fk("products.id", ondelete="CASCADE")
    location_id: Mapped[uuid.UUID] = _fk("locations.id")
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=Decimal(0))
    expires_at: Mapped[date | None] = mapped_column(Date)
    opened_at: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _updated()
    change_seq: Mapped[int] = _change_seq()
    change_xid: Mapped[int] = _change_xid()

    __table_args__ = (
        Index("ix_stock_batches_product", "household_id", "product_id"),
        Index("ix_stock_batches_location", "household_id", "location_id"),
        Index("ix_stock_batches_expires", "household_id", "expires_at"),
    )


class StockTransaction(Base):
    """Append-only audit trail. Only ``undone`` is ever updated."""

    __tablename__ = "stock_transactions"
    id: Mapped[uuid.UUID] = _pk()
    household_id: Mapped[uuid.UUID] = _fk("households.id", ondelete="CASCADE")
    client_op_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    type: Mapped[str] = mapped_column(String(16))
    quantity_delta: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    product_id: Mapped[uuid.UUID] = _fk("products.id")
    batch_id: Mapped[uuid.UUID | None] = _fk("stock_batches.id", nullable=True)
    location_id: Mapped[uuid.UUID | None] = _fk("locations.id", nullable=True)
    to_location_id: Mapped[uuid.UUID | None] = _fk("locations.id", nullable=True)
    undoes_id: Mapped[uuid.UUID | None] = _fk("stock_transactions.id", nullable=True)
    undone: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    user_id: Mapped[uuid.UUID | None] = _fk("users.id", nullable=True, ondelete="SET NULL")
    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    device_name: Mapped[str | None] = mapped_column(Text)
    device_id: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    op_error: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = _ts()
    created_at: Mapped[datetime] = _ts()

    lines: Mapped[list["StockTransactionLine"]] = relationship(
        lazy="selectin", order_by="StockTransactionLine.seq"
    )

    __table_args__ = (
        UniqueConstraint(
            "household_id", "client_op_id", name="uq_stock_transactions_household_client_op"
        ),
        Index("ix_stock_transactions_product", "household_id", "product_id", "created_at"),
        Index("ix_stock_transactions_created", "household_id", "created_at"),
    )


class StockTransactionLine(Base):
    """Per-batch effect of a transaction; lets undo reverse precisely what happened."""

    __tablename__ = "stock_transaction_lines"
    id: Mapped[uuid.UUID] = _pk()
    transaction_id: Mapped[uuid.UUID] = _fk("stock_transactions.id", ondelete="CASCADE")
    batch_id: Mapped[uuid.UUID] = _fk("stock_batches.id")
    seq: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    delta: Mapped[Decimal] = mapped_column(Numeric(12, 3))

    __table_args__ = (Index("ix_stock_transaction_lines_txn", "transaction_id"),)


class ShoppingItem(Base):
    __tablename__ = "shopping_items"
    id: Mapped[uuid.UUID] = _pk()
    household_id: Mapped[uuid.UUID] = _fk("households.id", ondelete="CASCADE")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    product_id: Mapped[uuid.UUID | None] = _fk("products.id", nullable=True, ondelete="SET NULL")
    name: Mapped[str] = mapped_column(Text)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=Decimal(1))
    unit: Mapped[str | None] = mapped_column(String(8))
    category_id: Mapped[uuid.UUID | None] = _fk("categories.id", nullable=True, ondelete="SET NULL")
    note: Mapped[str | None] = mapped_column(Text)
    checked: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(16), default="manual", server_default="manual")
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index(
            "uq_shopping_open_product",
            "household_id",
            "product_id",
            unique=True,
            postgresql_where=text(
                "checked = false AND product_id IS NOT NULL AND deleted_at IS NULL"
            ),
        ),
        Index("ix_shopping_household", "household_id"),
    )


class LookupCache(Base):
    __tablename__ = "lookup_cache"
    id: Mapped[uuid.UUID] = _pk()
    code: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))  # found | not_found | error
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    fetched_at: Mapped[datetime] = _ts()
    retry_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (UniqueConstraint("code", "provider", name="uq_lookup_cache_code_provider"),)


class LookupAttempt(Base):
    __tablename__ = "lookup_attempts"
    id: Mapped[uuid.UUID] = _pk()
    household_id: Mapped[uuid.UUID | None] = _fk("households.id", nullable=True, ondelete="CASCADE")
    product_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    code: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))
    http_status: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _ts()

    __table_args__ = (
        Index("ix_lookup_attempts_created", "created_at"),
        Index("ix_lookup_attempts_code", "code"),
        Index("ix_lookup_attempts_status", "status", "created_at"),
    )


class EnrichmentQueue(Base):
    __tablename__ = "enrichment_queue"
    id: Mapped[uuid.UUID] = _pk()
    household_id: Mapped[uuid.UUID] = _fk("households.id", ondelete="CASCADE")
    product_id: Mapped[uuid.UUID] = _fk("products.id", ondelete="CASCADE")
    code: Mapped[str] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    next_attempt_at: Mapped[datetime] = _ts()
    status: Mapped[str] = mapped_column(
        String(16), default="pending", server_default="pending"
    )  # pending | running | done | failed
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()

    __table_args__ = (
        UniqueConstraint("product_id", "code", name="uq_enrichment_queue_product_code"),
        Index("ix_enrichment_queue_due", "status", "next_attempt_at"),
    )


class ProviderSetting(Base):
    """Server-side admin overrides for lookup providers (NULL = use the environment default)."""

    __tablename__ = "provider_settings"
    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    enabled: Mapped[bool | None] = mapped_column(Boolean)
    priority: Mapped[int | None] = mapped_column(Integer)
    api_key: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = _ts()


class CatalogueSeed(Base):
    """Global (not household-scoped) read-only seed catalogue of retail barcodes.

    Imported from ``data/seed/*.jsonl.gz`` (Open Food Facts metadata, ODbL); see
    ``docs/data-licences.md``. Never written by request handlers.
    """

    __tablename__ = "catalogue_seed"
    code: Mapped[str] = mapped_column(String(14), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    brand: Mapped[str | None] = mapped_column(Text)
    package_size: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    package_unit: Mapped[str | None] = mapped_column(String(8))
    category_hint: Mapped[str | None] = mapped_column(Text)
    allergens: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    countries: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    source: Mapped[str] = mapped_column(String(32))
    license: Mapped[str] = mapped_column(Text)
    dataset_version: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = _ts()

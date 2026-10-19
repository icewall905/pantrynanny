"""recipes, recipe ingredients and the meal plan (new tables only)

Revision ID: 0007
Revises: 0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, UUID

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _id() -> sa.Column:
    return sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"))


def _ts(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=None if nullable else sa.func.now(),
        nullable=nullable,
    )


def upgrade() -> None:
    op.create_table(
        "recipes",
        _id(),
        sa.Column("household_id", UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("servings", sa.Integer(), server_default=sa.text("4"), nullable=False),
        sa.Column("prep_min", sa.Integer()),
        sa.Column("cook_min", sa.Integer()),
        sa.Column("instructions", ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("tags", ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("source_url", sa.Text()),
        sa.Column("source_name", sa.Text()),
        sa.Column("image_url", sa.Text()),
        sa.Column("created_by", UUID(as_uuid=True)),
        _ts("created_at"),
        _ts("updated_at"),
        _ts("deleted_at", nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_recipes"),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["households.id"],
            name="fk_recipes_household_id_households",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name="fk_recipes_created_by_users", ondelete="SET NULL"
        ),
    )
    op.create_index("ix_recipes_household", "recipes", ["household_id"])
    op.create_table(
        "recipe_ingredients",
        _id(),
        sa.Column("recipe_id", UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("raw", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 3)),
        sa.Column("unit", sa.String(16)),
        sa.Column("note", sa.Text()),
        sa.Column("optional", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("product_id", UUID(as_uuid=True)),
        sa.PrimaryKeyConstraint("id", name="pk_recipe_ingredients"),
        sa.ForeignKeyConstraint(
            ["recipe_id"],
            ["recipes.id"],
            name="fk_recipe_ingredients_recipe_id_recipes",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name="fk_recipe_ingredients_product_id_products",
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_recipe_ingredients_recipe", "recipe_ingredients", ["recipe_id"])
    op.create_table(
        "meal_plan_entries",
        _id(),
        sa.Column("household_id", UUID(as_uuid=True), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("slot", sa.String(16), server_default="dinner", nullable=False),
        sa.Column("recipe_id", UUID(as_uuid=True)),
        sa.Column("title", sa.Text()),
        sa.Column("servings", sa.Integer()),
        sa.Column("note", sa.Text()),
        _ts("cooked_at", nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.PrimaryKeyConstraint("id", name="pk_meal_plan_entries"),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["households.id"],
            name="fk_meal_plan_entries_household_id_households",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["recipe_id"],
            ["recipes.id"],
            name="fk_meal_plan_entries_recipe_id_recipes",
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_meal_plan_household_day", "meal_plan_entries", ["household_id", "day"])


def downgrade() -> None:
    op.drop_table("meal_plan_entries")
    op.drop_table("recipe_ingredients")
    op.drop_table("recipes")

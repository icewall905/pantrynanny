from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from .common import Qty

Slot = Literal["breakfast", "lunch", "dinner", "snack"]
IngredientStatus = Literal["have", "low", "missing", "staple", "optional"]


def _http_or_none(v: str | None) -> str | None:
    if v is None or v == "":
        return None
    if not v.startswith(("https://", "http://")):
        raise ValueError("must be an http(s) URL")
    return v


class IngredientIn(BaseModel):
    raw: str = Field(min_length=1, max_length=300)
    product_id: UUID | None = None
    optional: bool | None = None


class RecipeIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    servings: int = Field(default=4, ge=1, le=100)
    prep_min: int | None = Field(default=None, ge=0, le=10_000)
    cook_min: int | None = Field(default=None, ge=0, le=10_000)
    instructions: list[str] = Field(default_factory=list, max_length=80)
    tags: list[str] = Field(default_factory=list, max_length=20)
    source_url: str | None = Field(default=None, max_length=1000)
    source_name: str | None = Field(default=None, max_length=120)
    image_url: str | None = Field(default=None, max_length=1000)
    ingredients: list[IngredientIn] = Field(default_factory=list, max_length=100)

    _urls = field_validator("source_url", "image_url")(_http_or_none)

    @field_validator("instructions")
    @classmethod
    def _steps(cls, v: list[str]) -> list[str]:
        return [s.strip()[:2000] for s in v if s.strip()]

    @field_validator("tags")
    @classmethod
    def _tags(cls, v: list[str]) -> list[str]:
        return list(dict.fromkeys(t.strip()[:40] for t in v if t.strip()))


class IngredientOut(BaseModel):
    id: UUID
    position: int
    raw: str
    name: str
    quantity: Qty | None
    unit: str | None
    note: str | None
    optional: bool
    product_id: UUID | None


class RecipeOut(BaseModel):
    id: UUID
    version: int
    title: str
    description: str | None
    servings: int
    prep_min: int | None
    cook_min: int | None
    instructions: list[str]
    tags: list[str]
    source_url: str | None
    source_name: str | None
    image_url: str | None
    ingredients: list[IngredientOut]
    created_at: datetime
    updated_at: datetime


class MatchedProduct(BaseModel):
    id: UUID
    name: str
    total_quantity: Qty
    stock_unit: str
    image_url: str | None
    next_expiry: date | None


class IngredientAvailability(BaseModel):
    ingredient: IngredientOut
    status: IngredientStatus
    product: MatchedProduct | None
    linked: bool  # matched by an explicit link (vs. by name)
    need: Qty | None  # in the product's stock unit, for the requested servings
    enough: bool | None  # None = cannot tell (units not comparable)
    expiring: bool


class Availability(BaseModel):
    recipe_id: UUID
    servings: int
    have: int
    missing: int
    required: int
    coverage: float  # 0..1 over required, non-staple ingredients
    uses_expiring: list[str]
    items: list[IngredientAvailability]


class RecipeSummary(BaseModel):
    recipe: RecipeOut
    availability: Availability


class RecipeDraftOut(BaseModel):
    """An imported recipe for the user to review; nothing is saved yet."""

    title: str
    description: str | None
    servings: int | None
    prep_min: int | None
    cook_min: int | None
    ingredients: list[str]
    instructions: list[str]
    tags: list[str]
    image_url: str | None
    source_url: str
    source_name: str | None


class ImportIn(BaseModel):
    url: str = Field(min_length=8, max_length=1000)


class ShoppingFromIn(BaseModel):
    servings: int | None = Field(default=None, ge=1, le=100)
    ingredient_ids: list[UUID] | None = None  # default: everything missing


class ShoppingFromOut(BaseModel):
    added: list[str]
    skipped: list[str]


class ParseIn(BaseModel):
    lines: list[str] = Field(max_length=100)


class ParsedLine(BaseModel):
    raw: str
    name: str
    quantity: Qty | None
    unit: str | None
    note: str | None
    optional: bool


class MealIn(BaseModel):
    day: date
    slot: Slot = "dinner"
    recipe_id: UUID | None = None
    title: str | None = Field(default=None, max_length=200)
    servings: int | None = Field(default=None, ge=1, le=100)
    note: str | None = Field(default=None, max_length=500)


class MealPatch(BaseModel):
    day: date | None = None
    slot: Slot | None = None
    servings: int | None = Field(default=None, ge=1, le=100)
    note: str | None = Field(default=None, max_length=500)
    title: str | None = Field(default=None, max_length=200)
    cooked: bool | None = None


class MealOut(BaseModel):
    id: UUID
    day: date
    slot: str
    recipe_id: UUID | None
    recipe_title: str | None
    title: str | None
    servings: int | None
    note: str | None
    cooked_at: datetime | None
    missing: int | None  # required ingredients not in stock (recipe entries only)


class PlanShoppingIn(BaseModel):
    start: date
    days: int = Field(default=7, ge=1, le=31)

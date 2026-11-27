import re
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from .common import Qty

Slot = Literal["breakfast", "lunch", "dinner", "snack"]
Course = Literal[
    "breakfast", "lunch", "dinner", "side", "dessert", "baking", "drink", "snack", "condiment"
]
IngredientStatus = Literal["have", "low", "missing", "staple", "optional"]


def _http_or_none(v: str | None) -> str | None:
    if v is None or v == "":
        return None
    if not v.startswith(("https://", "http://")):
        raise ValueError("must be an http(s) URL")
    return v


_LOCAL_IMAGE = re.compile(r"^/api/media/[0-9a-f]{32}\.webp$")


def _image_url(v: str | None) -> str | None:
    """An http(s) URL, or one of our own stored images (e.g. copied in by an import)."""
    if v and _LOCAL_IMAGE.match(v):
        return v
    return _http_or_none(v)


def _labels(v: list[str]) -> list[str]:
    return list(dict.fromkeys(t.strip()[:40] for t in v if t.strip()))


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
    # left out on update: kept as they were (older clients do not know about categories)
    categories: list[str] = Field(default_factory=list, max_length=20)
    # left out: worked out from the tags/title/ingredients on create, kept as it was on update
    course: Course | None = None
    source_url: str | None = Field(default=None, max_length=1000)
    source_name: str | None = Field(default=None, max_length=120)
    image_url: str | None = Field(default=None, max_length=1000)
    ingredients: list[IngredientIn] = Field(default_factory=list, max_length=100)

    _urls = field_validator("source_url")(_http_or_none)
    _image = field_validator("image_url")(_image_url)

    @field_validator("instructions")
    @classmethod
    def _steps(cls, v: list[str]) -> list[str]:
        return [s.strip()[:2000] for s in v if s.strip()]

    _tags = field_validator("tags", "categories")(_labels)


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
    categories: list[str] = Field(default_factory=list)
    course: Course | None = None
    minutes: int | None = None  # prep_min + cook_min, None when neither is known
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


class RecipeBrief(BaseModel):
    """`include=summary`: one flat row per recipe for machine clients (no instructions or
    ingredient objects)."""

    id: UUID
    title: str
    course: Course | None
    tags: list[str]
    categories: list[str] = Field(default_factory=list)
    servings: int
    prep_min: int | None
    cook_min: int | None
    minutes: int | None
    source_url: str | None
    coverage: float
    have: int
    required: int
    missing: int
    missing_names: list[str]
    low_names: list[str]
    staple_names: list[str]
    uses_expiring: list[str]


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
    course: Course | None = None


class ImportIn(BaseModel):
    url: str = Field(min_length=8, max_length=1000)
    # the recipe's structured data as the browser sees it (browser extension): read instead of
    # fetching the page, so sites that block servers or build the page in script still work
    html: str | None = Field(default=None, max_length=2_000_000)


class ImportSavedOut(BaseModel):
    recipe: RecipeOut
    created: bool  # false: a recipe from this page was already saved


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

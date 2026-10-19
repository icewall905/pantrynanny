from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

MAX_MESSAGES = 30
MAX_MESSAGE_CHARS = 4000


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)

    @model_validator(mode="after")
    def _check(self):
        if not self.content.strip():
            raise ValueError("content must not be blank")
        if len(self.content) > MAX_MESSAGE_CHARS:
            if self.role == "user":
                raise ValueError(f"content must be at most {MAX_MESSAGE_CHARS} characters")
            # Over-long assistant history is truncated rather than rejected.
            self.content = self.content[:MAX_MESSAGE_CHARS]
        return self


class ChatIn(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=MAX_MESSAGES)
    locale: Literal["da", "en"] = "da"

    @field_validator("messages")
    @classmethod
    def _ends_with_user(cls, v: list[ChatMessage]) -> list[ChatMessage]:
        if v[-1].role != "user":
            raise ValueError("last message must be from the user")
        return v


class ToolCallOut(BaseModel):
    name: str
    arguments: dict


class Proposal(BaseModel):
    """An action the assistant suggests. Shown as a button; only the user can carry it out
    (through the normal, validated endpoints)."""

    id: str
    kind: Literal["shopping_add", "meal_plan", "consume"]
    label: str
    payload: dict


class ChatOut(BaseModel):
    reply: str
    tool_calls: list[ToolCallOut]
    model: str | None
    proposals: list[Proposal] = Field(default_factory=list)


class RecipesIn(BaseModel):
    prompt: str | None = Field(default=None, max_length=500)
    count: int = Field(default=3, ge=1, le=5)
    locale: Literal["da", "en"] = "da"


class Recipe(BaseModel):
    title: str
    description: str = ""
    have: list[str] = []
    missing: list[str] = []
    substitutions: list[str] = []
    steps: list[str] = []


class RecipesOut(BaseModel):
    recipes: list[Recipe]
    model: str | None = None


class PhotoSuggestion(BaseModel):
    name: str | None = None
    brand: str | None = None
    package_size: float | None = None
    package_unit: str | None = None
    category_guess: str | None = None
    confidence: float = 0.0


class StatusOut(BaseModel):
    enabled: bool
    reachable: bool
    model: str | None
    features: dict[str, bool] = Field(default_factory=dict)

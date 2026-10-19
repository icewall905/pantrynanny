from typing import Literal

from pydantic import BaseModel, Field, field_validator

MAX_MESSAGES = 30
MAX_MESSAGE_CHARS = 4000


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)

    @field_validator("content")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("content must not be blank")
        return v


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


class ChatOut(BaseModel):
    reply: str
    tool_calls: list[ToolCallOut]
    model: str | None


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

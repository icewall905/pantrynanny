from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, PlainSerializer

# Largest magnitude accepted in a single operation / shopping quantity.
MAX_OP_QTY = 1_000_000

# Quantities are stored NUMERIC(12,3) and serialised as plain JSON numbers.
Qty = Annotated[Decimal, PlainSerializer(float, return_type=float, when_used="json")]

Unit = Literal["pcs", "pkg", "g", "kg", "ml", "cl", "dl", "l"]
Role = Literal["owner", "admin", "member"]
ProductStatus = Literal["known", "unknown", "needs_review"]
TxnType = Literal["add", "remove", "adjust", "move", "undo"]
Symbology = Literal[
    "ean_13",
    "ean_8",
    "upc_a",
    "upc_e",
    "code_128",
    "code_39",
    "itf",
    "qr",
    "data_matrix",
    "other",
]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


__all__ = [
    "ORM",
    "Qty",
    "Unit",
    "Role",
    "ProductStatus",
    "TxnType",
    "Symbology",
    "date",
    "datetime",
    "UUID",
]

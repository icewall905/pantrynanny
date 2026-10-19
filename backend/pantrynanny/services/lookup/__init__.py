"""External product lookup (provider adapters, cache, enrichment helpers).

The rest of the backend depends on ``ProductData``, ``lookup_external`` and ``enqueue_enrichment``.
See ``docs/product-data-sources.md`` for the data sources, licences and limits.
"""

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import EnrichmentQueue, Product
from .providers import ProductData
from .service import (
    LookupOutcome,
    apply_product_data,
    enrich_product,
    lookup_detailed,
    lookup_external,
    new_product_from_data,
    refresh_product,
)

__all__ = [
    "LookupOutcome",
    "ProductData",
    "apply_product_data",
    "enqueue_enrichment",
    "enrich_product",
    "lookup_detailed",
    "lookup_external",
    "new_product_from_data",
    "refresh_product",
]


async def enqueue_enrichment(session: AsyncSession, product: Product) -> None:
    """Queue background enrichment for every barcode of ``product`` (idempotent)."""
    for bc in product.barcodes:
        if bc.code.startswith(("local:", "instore:")):
            continue
        stmt = (
            insert(EnrichmentQueue)
            .values(household_id=product.household_id, product_id=product.id, code=bc.code)
            .on_conflict_do_nothing(constraint="uq_enrichment_queue_product_code")
        )
        await session.execute(stmt)

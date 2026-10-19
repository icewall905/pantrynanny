"""Provider adapters. Every adapter talks to an *official* API only (no scraping)."""

import re
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal, Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import Settings
from ...models import CatalogueSeed
from . import runtime
from .parsing import allergen_names, map_category, parse_quantity, provider_code


@dataclass(slots=True)
class ProductData:
    """Provider-neutral product metadata returned by a lookup."""

    name: str
    brand: str | None = None
    package_size: float | None = None
    package_unit: str | None = None
    category_hint: str | None = None
    image_url: str | None = None
    ingredients: str | None = None
    allergens: list[str] = field(default_factory=list)
    nutrition: dict[str, Any] | None = None
    countries: list[str] = field(default_factory=list)
    description: str | None = None
    source: str = "external"
    source_attribution: str | None = None
    confidence: float | None = None


@dataclass(slots=True)
class ProviderResult:
    status: Literal["found", "not_found", "error"]
    data: ProductData | None = None
    raw: dict[str, Any] | None = None
    http_status: int | None = None
    error: str | None = None
    retry_after_s: float | None = None
    rate_limited: bool = False  # nothing was sent; do not cache


class Provider(Protocol):
    name: str
    display_name: str
    license: str
    attribution: str
    requires_key: bool
    default_priority: int
    default_enabled: bool

    def enabled(self) -> bool: ...

    def rate_per_min(self) -> float: ...

    async def fetch(self, code: str, timeout_s: float | None = None) -> ProviderResult: ...


def confidence_for(d: ProductData) -> float:
    """Completeness-based confidence in [0, 0.95]; below 0.6 the product needs review."""
    score = 0.45
    if d.brand:
        score += 0.15
    if d.package_size and d.package_unit:
        score += 0.10
    if d.image_url:
        score += 0.10
    if d.category_hint:
        score += 0.05
    if d.ingredients:
        score += 0.05
    if d.nutrition:
        score += 0.05
    return round(min(score, 0.95), 2)


_NUTRIENTS = {
    "energy-kcal_100g": "energy_kcal",
    "fat_100g": "fat",
    "saturated-fat_100g": "saturated_fat",
    "carbohydrates_100g": "carbohydrates",
    "sugars_100g": "sugars",
    "fiber_100g": "fiber",
    "proteins_100g": "proteins",
    "salt_100g": "salt",
}
OFF_FIELDS = ",".join(
    [
        "code",
        "product_name",
        "product_name_da",
        "product_name_en",
        "generic_name",
        "generic_name_da",
        "generic_name_en",
        "brands",
        "quantity",
        "categories_tags",
        "image_front_url",
        "image_url",
        "ingredients_text",
        "ingredients_text_da",
        "ingredients_text_en",
        "allergens_tags",
        "nutriments",
        "countries_tags",
    ]
)


def _first(*values: Any) -> str | None:
    for v in values:
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _retry_after(resp: httpx.Response) -> float | None:
    v = resp.headers.get("retry-after")
    return float(v) if v and v.replace(".", "", 1).isdigit() else None


class OpenFoodFactsProvider:
    """Open Food Facts v2 product API (ODbL data, CC BY-SA images)."""

    name: ClassVar[str] = "openfoodfacts"
    display_name: ClassVar[str] = "Open Food Facts"
    license: ClassVar[str] = "ODbL 1.0 (database), DbCL (contents), CC BY-SA (images)"
    attribution: ClassVar[str] = "Open Food Facts – ODbL (images CC BY-SA)"
    requires_key: ClassVar[bool] = False
    default_priority: ClassVar[int] = 10
    default_enabled: ClassVar[bool] = True

    def __init__(
        self,
        settings: Settings,
        *,
        override_enabled: bool | None = None,
        api_key: str | None = None,
    ):
        self.settings = settings
        self.override_enabled = override_enabled
        self.api_key = api_key

    @property
    def base_url(self) -> str:
        return self.settings.off_base_url.rstrip("/")

    def enabled(self) -> bool:
        if self.override_enabled is not None:
            return self.override_enabled
        return self.settings.off_enabled

    def rate_per_min(self) -> float:
        s = self.settings
        return s.off_worker_rate_per_min if runtime.role == "worker" else s.off_rate_per_min

    async def fetch(self, code: str, timeout_s: float | None = None) -> ProviderResult:
        pc = provider_code(code)
        if pc is None:
            return ProviderResult("not_found")
        url = f"{self.base_url}/api/v2/product/{pc}.json"
        try:
            resp = await runtime.get_client().get(
                url,
                params={"fields": OFF_FIELDS},
                timeout=timeout_s or self.settings.lookup_timeout_s,
            )
        except httpx.HTTPError as exc:
            return ProviderResult("error", error=f"{type(exc).__name__}: {exc}"[:300])
        if resp.status_code == 404:
            return ProviderResult("not_found", http_status=404)
        if resp.status_code != 200:
            return ProviderResult(
                "error",
                http_status=resp.status_code,
                error=f"HTTP {resp.status_code}",
                retry_after_s=_retry_after(resp),
            )
        try:
            body = resp.json()
        except ValueError:
            return ProviderResult("error", http_status=200, error="invalid JSON")
        product = body.get("product") if isinstance(body, dict) else None
        if not isinstance(product, dict) or body.get("status") == 0:
            return ProviderResult("not_found", http_status=200)
        data = self.map_product(product)
        if data is None:
            return ProviderResult("not_found", http_status=200, raw=product)
        return ProviderResult("found", data=data, raw=product, http_status=200)

    def map_product(self, p: dict[str, Any]) -> ProductData | None:
        # Danish first, then English; the "main language" fields can be any language (Polish
        # butter in a Danish shop), so they come last.
        name = _first(
            p.get("product_name_da"),
            p.get("product_name_en"),
            p.get("product_name"),
            p.get("generic_name_da"),
            p.get("generic_name_en"),
            p.get("generic_name"),
        )
        if not name:
            return None
        brands = _first(p.get("brands"))
        brand = brands.split(",")[0].strip() if brands else None
        size, unit, note = parse_quantity(p.get("quantity"))
        generic = _first(p.get("generic_name_da"), p.get("generic_name_en"), p.get("generic_name"))
        desc_parts = []
        if generic and generic.lower() != name.lower():
            desc_parts.append(generic)
        if note:
            desc_parts.append(note)
        nutriments = p.get("nutriments") or {}
        nutrition = {
            out: nutriments[key]
            for key, out in _NUTRIENTS.items()
            if isinstance(nutriments.get(key), int | float)
        }
        if nutrition:
            nutrition["per"] = "100 g"
        countries = [
            t.split(":", 1)[-1].replace("-", " ").title() for t in p.get("countries_tags") or []
        ]
        data = ProductData(
            name=name[:200],
            brand=brand[:200] if brand else None,
            package_size=size,
            package_unit=unit,
            category_hint=map_category(p.get("categories_tags")),
            image_url=_first(p.get("image_front_url"), p.get("image_url")),
            ingredients=_first(
                p.get("ingredients_text_da"),
                p.get("ingredients_text_en"),
                p.get("ingredients_text"),
            ),
            allergens=allergen_names(p.get("allergens_tags")),
            nutrition=nutrition or None,
            countries=countries,
            description=" – ".join(desc_parts) or None,
            source=self.name,
            source_attribution=self.attribution,
        )
        data.confidence = confidence_for(data)
        return data


class OpenBeautyFactsProvider(OpenFoodFactsProvider):
    name = "openbeautyfacts"
    display_name = "Open Beauty Facts"
    attribution = "Open Beauty Facts – ODbL (images CC BY-SA)"
    default_priority = 20
    # On by default: only asked after Open Food Facts misses (household and non-food items).
    default_enabled = True

    @property
    def base_url(self) -> str:
        return "https://world.openbeautyfacts.org"

    def enabled(self) -> bool:
        if self.override_enabled is not None:
            return self.override_enabled
        return self.settings.off_enabled and self.settings.off_sisters_enabled


class OpenPetFoodFactsProvider(OpenBeautyFactsProvider):
    name = "openpetfoodfacts"
    display_name = "Open Pet Food Facts"
    attribution = "Open Pet Food Facts – ODbL (images CC BY-SA)"
    default_priority = 21

    @property
    def base_url(self) -> str:
        return "https://world.openpetfoodfacts.org"


class OpenProductsFactsProvider(OpenBeautyFactsProvider):
    name = "openproductsfacts"
    display_name = "Open Products Facts"
    attribution = "Open Products Facts – ODbL (images CC BY-SA)"
    default_priority = 22

    @property
    def base_url(self) -> str:
        return "https://world.openproductsfacts.org"


class EanSearchProvider:
    """EAN-Search.org REST API (paid token). Disabled unless a token is configured."""

    name = "eansearch"
    display_name = "EAN-Search.org"
    license = "Commercial API terms of ean-search.org (token holder)"
    attribution = "EAN-Search.org"
    requires_key = True
    default_priority = 50
    default_enabled = False

    def __init__(
        self,
        settings: Settings,
        *,
        override_enabled: bool | None = None,
        api_key: str | None = None,
    ):
        self.settings = settings
        self.override_enabled = override_enabled
        self.api_key = api_key or settings.eansearch_token or None

    def enabled(self) -> bool:
        if not self.api_key:
            return False
        return self.override_enabled if self.override_enabled is not None else True

    def rate_per_min(self) -> float:
        return self.settings.eansearch_rate_per_min

    async def fetch(self, code: str, timeout_s: float | None = None) -> ProviderResult:
        pc = provider_code(code)
        if pc is None or not self.api_key:
            return ProviderResult("not_found")
        try:
            resp = await runtime.get_client().get(
                f"{self.settings.eansearch_base_url.rstrip('/')}/api",
                params={
                    "token": self.api_key,
                    "op": "barcode-lookup",
                    "ean": pc,
                    "format": "json",
                    "language": 1,  # English names; the API has no Danish option
                },
                timeout=timeout_s or self.settings.lookup_timeout_s,
            )
        except httpx.HTTPError as exc:
            # never leak the token through the exception text
            msg = re.sub(r"token=[^&\s]+", "token=***", f"{type(exc).__name__}: {exc}")
            return ProviderResult("error", error=msg[:300])
        if resp.status_code in (401, 402, 403):
            return ProviderResult(
                "error", http_status=resp.status_code, error="authentication or quota error"
            )
        if resp.status_code != 200:
            return ProviderResult(
                "error",
                http_status=resp.status_code,
                error=f"HTTP {resp.status_code}",
                retry_after_s=_retry_after(resp),
            )
        try:
            body = resp.json()
        except ValueError:
            return ProviderResult("error", http_status=200, error="invalid JSON")
        item = body[0] if isinstance(body, list) and body else None
        if not isinstance(item, dict) or not _first(item.get("name")):
            return ProviderResult("not_found", http_status=200)
        data = ProductData(
            name=str(item["name"]).strip()[:200],
            category_hint=None,
            source=self.name,
            source_attribution=self.attribution,
        )
        size, unit, _ = parse_quantity(data.name)
        data.package_size, data.package_unit = size, unit
        country = _first(item.get("issuingCountry"))
        data.countries = [country] if country else []
        data.confidence = min(confidence_for(data), 0.5)  # name only: always flagged for review
        raw = {k: item.get(k) for k in ("ean", "name", "categoryName", "issuingCountry")}
        return ProviderResult("found", data=data, raw=raw, http_status=200)


# --- local seed catalogue ---
SEED_CONFIDENCE = 0.8  # >= 0.6: products created from the seed are "known"


class SeedCatalogueProvider:
    """Reads ``catalogue_seed``. Flagged ``local``: the lookup chain calls ``lookup(session)``
    instead of ``fetch`` and skips rate limiting and the HTTP-oriented lookup cache."""

    name: ClassVar[str] = "catalogue_seed"
    display_name: ClassVar[str] = "Seed catalogue (Open Food Facts, local)"
    license: ClassVar[str] = "ODbL 1.0 (database), DbCL 1.0 (contents)"
    attribution: ClassVar[str] = "Open Food Facts – ODbL"
    requires_key: ClassVar[bool] = False
    default_priority: ClassVar[int] = 1
    default_enabled: ClassVar[bool] = True
    local: ClassVar[bool] = True

    def __init__(
        self,
        settings: Settings,
        *,
        override_enabled: bool | None = None,
        api_key: str | None = None,
    ):
        self.settings = settings
        self.override_enabled = override_enabled

    def enabled(self) -> bool:
        if self.override_enabled is not None:
            return self.override_enabled
        return self.settings.seed_enabled

    def rate_per_min(self) -> float:
        return 0.0

    async def fetch(self, code: str, timeout_s: float | None = None) -> ProviderResult:
        raise NotImplementedError("local provider: use lookup(session, code)")

    async def lookup(self, session: AsyncSession, code: str) -> ProviderResult:
        row = (
            await session.execute(select(CatalogueSeed).where(CatalogueSeed.code == code))
        ).scalar_one_or_none()
        if row is None:
            return ProviderResult("not_found")
        data = ProductData(
            name=row.name[:200],
            brand=row.brand,
            package_size=float(row.package_size) if row.package_size is not None else None,
            package_unit=row.package_unit,
            category_hint=row.category_hint,
            allergens=list(row.allergens or []),
            countries=[c.replace("-", " ").title() for c in row.countries or []],
            source=self.name,
            source_attribution=self.attribution,
            confidence=SEED_CONFIDENCE,
        )
        return ProviderResult("found", data=data, raw={"dataset_version": row.dataset_version})


PROVIDER_CLASSES: list[type] = [
    SeedCatalogueProvider,
    OpenFoodFactsProvider,
    OpenBeautyFactsProvider,
    OpenPetFoodFactsProvider,
    OpenProductsFactsProvider,
    EanSearchProvider,
]
PROVIDER_NAMES = [c.name for c in PROVIDER_CLASSES]


@dataclass(slots=True)
class ProviderConfig:
    name: str
    enabled: bool | None = None
    priority: int | None = None
    api_key: str | None = None


def build_providers(settings: Settings, overrides: dict[str, ProviderConfig]) -> list[Any]:
    """Instantiate adapters with admin overrides applied, sorted by effective priority."""
    out = []
    for cls in PROVIDER_CLASSES:
        ov = overrides.get(cls.name)
        inst = cls(
            settings,
            override_enabled=ov.enabled if ov else None,
            api_key=ov.api_key if ov else None,
        )
        inst.priority = ov.priority if ov and ov.priority is not None else cls.default_priority
        out.append(inst)
    out.sort(key=lambda p: (p.priority, p.name))
    return out

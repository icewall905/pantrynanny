"""Runtime configuration (environment variables prefixed ``PN_`` and an optional ``.env``)."""

from functools import lru_cache
from urllib.parse import urlparse

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PN_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = "postgresql+asyncpg://pantrynanny:pantrynanny@127.0.0.1:5432/pantrynanny"
    public_url: str = "http://localhost:8000"
    # Comma separated extra CORS origins; the public URL origin is always allowed.
    cors_origins: str = ""
    # Comma separated IPs/CIDRs (or "*") whose X-Forwarded-* headers are trusted.
    trusted_proxies: str = "127.0.0.1"
    upload_dir: str = "/var/lib/pantrynanny/uploads"
    log_format: str = "json"  # json | console
    log_level: str = "INFO"
    timezone: str = "Europe/Copenhagen"

    lookup_timeout_s: float = 3.0
    off_enabled: bool = True
    off_base_url: str = "https://world.openfoodfacts.org"
    off_user_agent: str = "PantryNanny/1.0 (self-hosted household app)"
    eansearch_token: str = ""
    eansearch_base_url: str = "https://api.ean-search.org"
    # Open Food Facts allows 15 product reads/min/IP. The API process and the worker each hold a
    # bucket; together they stay below that limit.
    off_rate_per_min: int = 8
    off_worker_rate_per_min: int = 6
    eansearch_rate_per_min: int = 30
    image_download_max_bytes: int = 5 * 1024 * 1024
    upload_max_bytes: int = 8 * 1024 * 1024

    ai_base_url: str = ""
    ai_api_key: str = ""
    ai_model: str = ""
    ai_timeout_s: float = 90.0

    # Request body limits (bytes).
    max_json_body: int = 2 * 1024 * 1024
    max_upload_body: int = 10 * 1024 * 1024

    @field_validator("cors_origins")
    @classmethod
    def _no_wildcard_cors(cls, v: str) -> str:
        if "*" in v:
            raise ValueError("PN_CORS_ORIGINS must list explicit origins; '*' is not allowed")
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        origins = [o.strip().rstrip("/") for o in self.cors_origins.split(",") if o.strip()]
        parsed = urlparse(self.public_url)
        if parsed.scheme and parsed.netloc:
            origins.append(f"{parsed.scheme}://{parsed.netloc}")
        return list(dict.fromkeys(origins))

    @property
    def trusted_proxy_list(self) -> list[str]:
        return [p.strip() for p in self.trusted_proxies.split(",") if p.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

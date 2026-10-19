"""Process-wide lookup runtime: settings, shared HTTP client and process role (api | worker)."""

import httpx

from ...config import Settings
from ...config import get_settings as _env_settings
from ...logging import get_logger

log = get_logger("pantrynanny.lookup")
_settings: Settings | None = None
_client: httpx.AsyncClient | None = None
_client_ua: str | None = None
role: str = "api"


def get_settings() -> Settings:
    return _settings or _env_settings()


def set_settings(settings: Settings | None) -> None:
    """Override settings (tests, worker). ``None`` restores the environment defaults."""
    global _settings
    _settings = settings


def set_role(value: str) -> None:
    global role
    role = value


def get_client() -> httpx.AsyncClient:
    """One shared AsyncClient with the identifying User-Agent Open Food Facts asks for."""
    global _client, _client_ua
    ua = get_settings().off_user_agent
    if _client is None or _client.is_closed or _client_ua != ua:
        if "@" not in ua and "http" not in ua:
            log.warning(
                "off_user_agent_without_contact",
                hint="set PN_OFF_USER_AGENT to 'PantryNanny/1.0 (contact: you@example.com)'",
            )
        _client = httpx.AsyncClient(
            headers={"User-Agent": ua, "Accept": "application/json"},
            follow_redirects=False,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=4),
        )
        _client_ua = ua
    return _client


async def close_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None

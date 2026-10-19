"""Fetch a recipe page without letting the server be used to reach the local network (SSRF).

Every hop (redirects included) is resolved first; the request is refused unless *all* addresses
are public. The connection then goes to the address that was checked (pinned, with SNI/Host set
to the real name), so a DNS answer cannot change between the check and the request.
"""

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from ..errors import AppError

MAX_BYTES = 3_000_000
MAX_REDIRECTS = 4
UA = "PantryNanny/1.0 (+recipe import; self-hosted household app)"

Resolver = Callable[[str, int], Awaitable[list[str]]]


async def system_resolve(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(i[4][0] for i in infos))


def _public(ip: str) -> bool:
    addr = ipaddress.ip_address(ip.split("%", 1)[0])
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return addr.is_global and not addr.is_multicast


def _blocked(detail: str) -> AppError:
    return AppError(422, "import_blocked", detail)


async def fetch_page(
    url: str,
    *,
    resolve: Resolver = system_resolve,
    transport: httpx.AsyncBaseTransport | None = None,
    timeout_s: float = 10.0,
) -> tuple[str, str]:
    """Return (final_url, html). Raises AppError(422) for anything unsafe or unusable."""
    async with httpx.AsyncClient(
        transport=transport, timeout=timeout_s, follow_redirects=False, verify=True
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            parts = urlsplit(url)
            if parts.scheme not in ("http", "https") or not parts.hostname:
                raise _blocked("Only http(s) links to public websites can be imported.")
            if parts.username or parts.password:
                raise _blocked("Links with a user name or password are not allowed.")
            host = parts.hostname
            port = parts.port or (443 if parts.scheme == "https" else 80)
            if port not in (80, 443, 8080, 8443):
                raise _blocked("Only standard web ports are allowed.")
            try:
                addrs = await resolve(host, port)
            except OSError as e:
                raise AppError(422, "import_failed", f"Could not resolve {host}.") from e
            if not addrs or not all(_public(a) for a in addrs):
                raise _blocked("That address is on a private or local network and is not allowed.")
            ip = addrs[0]
            netloc = f"[{ip}]" if ":" in ip else ip
            if parts.port:
                netloc += f":{parts.port}"
            pinned = urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, ""))
            req = client.build_request(
                "GET",
                pinned,
                headers={
                    "Host": parts.netloc.rsplit("@", 1)[-1],
                    "User-Agent": UA,
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "da,en;q=0.8",
                },
                extensions={"sni_hostname": host} if parts.scheme == "https" else {},
            )
            try:
                resp = await client.send(req, stream=True)
            except httpx.HTTPError as e:
                raise AppError(
                    422, "import_failed", f"Could not load the page ({e.__class__.__name__})."
                ) from e
            try:
                if resp.is_redirect and resp.headers.get("location"):
                    url = urljoin(url, resp.headers["location"])
                    continue
                if resp.status_code >= 400:
                    raise AppError(
                        422, "import_failed", f"The website answered {resp.status_code}."
                    )
                ctype = resp.headers.get("content-type", "")
                if "html" not in ctype and "json" not in ctype:
                    raise AppError(422, "import_failed", "That link is not a web page.")
                body = bytearray()
                async for chunk in resp.aiter_bytes():
                    body += chunk
                    if len(body) > MAX_BYTES:
                        raise AppError(422, "import_failed", "The page is too large.")
                return url, body.decode(resp.encoding or "utf-8", errors="replace")
            finally:
                await resp.aclose()
    raise AppError(422, "import_failed", "Too many redirects.")

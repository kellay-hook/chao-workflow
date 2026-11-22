from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx


class UnsafeUrlError(ValueError):
    pass


@dataclass
class HttpResult:
    status_code: int
    headers: dict[str, str] = field(default_factory=dict)
    body: Any = None
    text: str = ""


def _host_allowed(host: str, allowed_domains: list[str]) -> bool:
    host = host.lower().rstrip(".")
    for domain in allowed_domains:
        domain = domain.lower().lstrip(".").rstrip(".")
        if host == domain or host.endswith("." + domain):
            return True
    return False


def _is_private_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


async def validate_public_url(url: str, allowed_domains: list[str] | None = None) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise UnsafeUrlError("only http and https URLs are allowed")
    if not parsed.hostname:
        raise UnsafeUrlError("URL has no hostname")
    allowed_domains = allowed_domains or []
    if _host_allowed(parsed.hostname, allowed_domains):
        return
    try:
        infos = await asyncio.to_thread(
            socket.getaddrinfo, parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)
        )
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"could not resolve host: {parsed.hostname}") from exc
    for info in infos:
        address = info[4][0]
        if _is_private_ip(address):
            raise UnsafeUrlError(f"private or reserved address blocked: {address}")


async def request_json(
    *,
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    body: Any = None,
    timeout_sec: int = 30,
    allowed_domains: list[str] | None = None,
) -> HttpResult:
    method = method.upper()
    current_url = url
    for _ in range(4):
        await validate_public_url(current_url, allowed_domains)
        async with httpx.AsyncClient(timeout=timeout_sec, follow_redirects=False) as client:
            response = await client.request(
                method,
                current_url,
                headers=headers,
                params=params,
                json=body if isinstance(body, (dict, list)) else None,
                content=body if isinstance(body, str) else None,
            )
        if response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("location")
            if not location:
                break
            current_url = str(httpx.URL(current_url).join(location))
            if response.status_code == 303:
                method = "GET"
            continue
        content = response.content[:2 * 1024 * 1024]
        text = content.decode(response.encoding or "utf-8", errors="replace")
        parsed: Any = text
        if "application/json" in response.headers.get("content-type", ""):
            try:
                parsed = response.json()
            except Exception:
                parsed = text
        return HttpResult(
            status_code=response.status_code,
            headers=dict(response.headers),
            body=parsed,
            text=text,
        )
    raise UnsafeUrlError("too many redirects")

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx
import jwt

from app.config import settings
from app.models import OAuthConnection, ensure_aware, utcnow
from app.security import decrypt_secret, encrypt_secret


class OAuthError(Exception):
    pass


def redirect_uri() -> str:
    return settings.public_base_url.rstrip("/") + "/api/v1/oauth/callback"


def frontend_base_url() -> str:
    return (settings.web_base_url or settings.public_base_url).rstrip("/")


def sign_state(connection: OAuthConnection, user_id: str | None) -> str:
    payload = {
        "connection_id": connection.id,
        "tenant_id": connection.tenant_id,
        "user_id": user_id,
        "type": "oauth_state",
        "exp": int((datetime.now(UTC) + timedelta(minutes=10)).timestamp()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_state(state: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(state, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise OAuthError("invalid OAuth state") from exc
    if payload.get("type") != "oauth_state":
        raise OAuthError("invalid OAuth state type")
    return payload


def authorize_url(connection: OAuthConnection, user_id: str | None) -> str:
    parsed = urlparse(connection.auth_url)
    query = dict(parse_qsl(parsed.query))
    query.update({"response_type": "code", "client_id": connection.client_id, "redirect_uri": redirect_uri(), "state": sign_state(connection, user_id)})
    if connection.scopes:
        query["scope"] = " ".join(connection.scopes)
    return urlunparse(parsed._replace(query=urlencode(query)))


async def _token_request(connection: OAuthConnection, data: dict[str, str]) -> dict[str, Any]:
    client_secret = decrypt_secret(connection.client_secret_ciphertext)
    auth = None
    if connection.token_auth_method == "client_secret_basic":
        auth = httpx.BasicAuth(connection.client_id, client_secret)
        data = {**data, "client_id": connection.client_id}
    else:
        data = {**data, "client_id": connection.client_id, "client_secret": client_secret}
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            connection.token_url,
            data=data,
            headers={"Accept": "application/json"},
            auth=auth,
        )
        if response.status_code >= 400:
            raise OAuthError(f"token endpoint HTTP {response.status_code}: {response.text[:800]}")
        try:
            return response.json()
        except Exception as exc:
            raise OAuthError("token endpoint did not return JSON") from exc


def _apply_tokens(connection: OAuthConnection, data: dict[str, Any]) -> None:
    access = data.get("access_token")
    if not access:
        raise OAuthError("token response did not include access_token")
    connection.access_token_ciphertext = encrypt_secret(str(access))
    if data.get("refresh_token"):
        connection.refresh_token_ciphertext = encrypt_secret(str(data["refresh_token"]))
    expires_in = data.get("expires_in")
    connection.expires_at = utcnow() + timedelta(seconds=int(expires_in)) if expires_in else None
    connection.status = "connected"
    connection.updated_at = utcnow()


async def exchange_code(connection: OAuthConnection, code: str) -> None:
    data = await _token_request(connection, {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri()})
    _apply_tokens(connection, data)


async def refresh(connection: OAuthConnection) -> None:
    if not connection.refresh_token_ciphertext:
        raise OAuthError("OAuth connection has no refresh token")
    data = await _token_request(connection, {"grant_type": "refresh_token", "refresh_token": decrypt_secret(connection.refresh_token_ciphertext)})
    _apply_tokens(connection, data)


async def access_token(connection: OAuthConnection) -> str:
    if connection.access_token_ciphertext:
        if not connection.expires_at or ensure_aware(connection.expires_at) > utcnow() + timedelta(seconds=60):
            return decrypt_secret(connection.access_token_ciphertext)
    await refresh(connection)
    return decrypt_secret(connection.access_token_ciphertext)

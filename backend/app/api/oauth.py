from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import audit
from app.db import get_session
from app.deps import Principal, audit_context, require_tenant
from app.models import OAuthConnection
from app.schemas import OAuthAuthorizeOut, OAuthConnectionCreate, OAuthConnectionOut
from app.security import encrypt_secret
from app.services import oauth

router = APIRouter(prefix="/api/v1", tags=["oauth"])


def _require_editor(principal: Principal) -> None:
    if principal.is_api_key or principal.role not in {"owner", "admin", "editor"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="editor required")


@router.get("/tenants/{tenant_id}/oauth-connections", response_model=list[OAuthConnectionOut])
async def list_oauth_connections(
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> list[OAuthConnection]:
    result = await session.execute(select(OAuthConnection).where(OAuthConnection.tenant_id == principal.tenant_id).order_by(OAuthConnection.created_at.desc()))
    return list(result.scalars().all())


@router.post("/tenants/{tenant_id}/oauth-connections", response_model=OAuthConnectionOut, status_code=status.HTTP_201_CREATED)
async def create_oauth_connection(
    payload: OAuthConnectionCreate,
    request: Request,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> OAuthConnection:
    _require_editor(principal)
    connection = OAuthConnection(
        tenant_id=principal.tenant_id,
        name=payload.name,
        auth_url=payload.auth_url,
        token_url=payload.token_url,
        client_id=payload.client_id,
        client_secret_ciphertext=encrypt_secret(payload.client_secret),
        token_auth_method=payload.token_auth_method,
        scopes=payload.scopes,
        created_by=principal.user_id,
    )
    session.add(connection)
    await audit(session, tenant_id=principal.tenant_id, actor_id=principal.user_id, action="oauth_connection.create", resource_type="oauth_connection", resource_id=connection.id, detail={"name": payload.name, "auth_url": payload.auth_url}, **audit_context(request))
    await session.commit()
    return connection


@router.delete("/tenants/{tenant_id}/oauth-connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_oauth_connection(
    connection_id: str,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> None:
    _require_editor(principal)
    connection = await session.get(OAuthConnection, connection_id)
    if connection and connection.tenant_id == principal.tenant_id:
        await session.delete(connection)
        await session.commit()


@router.post("/tenants/{tenant_id}/oauth-connections/{connection_id}/disconnect", response_model=OAuthConnectionOut)
async def disconnect_oauth_connection(
    connection_id: str,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> OAuthConnection:
    _require_editor(principal)
    connection = await session.get(OAuthConnection, connection_id)
    if not connection or connection.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="OAuth connection not found")
    connection.access_token_ciphertext = ""
    connection.refresh_token_ciphertext = ""
    connection.expires_at = None
    connection.status = "disconnected"
    await session.commit()
    return connection


@router.get("/tenants/{tenant_id}/oauth-connections/{connection_id}/authorize-url", response_model=OAuthAuthorizeOut)
async def get_authorize_url(
    connection_id: str,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> OAuthAuthorizeOut:
    _require_editor(principal)
    connection = await session.get(OAuthConnection, connection_id)
    if not connection or connection.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="OAuth connection not found")
    return OAuthAuthorizeOut(authorize_url=oauth.authorize_url(connection, principal.user_id))


@router.get("/oauth/callback")
async def oauth_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    base = oauth.frontend_base_url()
    if error or not code or not state:
        return RedirectResponse(f"{base}/tools?oauth=error&message={quote(error or 'missing code or state')}")
    connection = None
    try:
        payload = oauth.decode_state(state)
        connection = await session.get(OAuthConnection, str(payload.get("connection_id") or ""))
        if not connection:
            raise oauth.OAuthError("OAuth connection not found")
        await oauth.exchange_code(connection, code)
        await session.commit()
        return RedirectResponse(f"{base}/tools?oauth=success&connection={connection.id}")
    except Exception as exc:
        if connection:
            connection.status = "error"
            await session.commit()
        return RedirectResponse(f"{base}/tools?oauth=error&message={quote(str(exc)[:300])}")

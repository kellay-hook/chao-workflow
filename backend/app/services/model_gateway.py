from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import ModelProfile
from app.services.secrets import get_secret_value


class ModelError(Exception):
    pass


@dataclass
class ChatResult:
    content: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tokens: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


def _profile_dict(profile: ModelProfile | dict[str, Any]) -> dict[str, Any]:
    if isinstance(profile, ModelProfile):
        return {
            "id": profile.id,
            "provider": profile.provider,
            "base_url": profile.base_url,
            "model": profile.model,
            "api_key_secret": profile.api_key_secret,
            "max_tokens": profile.max_tokens,
            "temperature": profile.temperature,
            "timeout_sec": profile.timeout_sec,
            "embedding_dimension": profile.embedding_dimension,
        }
    return profile


async def _api_key(session: AsyncSession, tenant_id: str, profile: dict[str, Any]) -> str:
    ref = profile.get("api_key_secret") or ""
    if not ref:
        return profile.get("api_key") or ""
    if ref.startswith("sk-") or ref.startswith("Bearer "):
        return ref.removeprefix("Bearer ")
    if ref.startswith("${secret:") and ref.endswith("}"):
        ref = ref[len("${secret:") : -1]
    value = await get_secret_value(session, tenant_id, ref)
    if value is None:
        raise ModelError(f"model credential secret '{ref}' not found")
    return value


async def resolve_chat_profile(
    session: AsyncSession, tenant_id: str, profile_id: str | None
) -> dict[str, Any]:
    profile: ModelProfile | None = None
    if profile_id:
        profile = await session.get(ModelProfile, profile_id)
    if profile is None:
        result = await session.execute(
            select(ModelProfile).where(
                ModelProfile.tenant_id == tenant_id, ModelProfile.is_default.is_(True)
            )
        )
        profile = result.scalars().first()
    if profile:
        data = _profile_dict(profile)
        data["api_key"] = await _api_key(session, tenant_id, data)
        return data
    return {
        "id": None,
        "provider": "openai_compatible",
        "base_url": settings.default_chat_base_url,
        "model": settings.default_chat_model,
        "api_key": settings.default_chat_api_key,
        "max_tokens": 2048,
        "temperature": 0.2,
        "timeout_sec": 120,
        "embedding_dimension": settings.default_embedding_dimension,
    }


async def resolve_embedding_profile(
    session: AsyncSession, tenant_id: str, profile_id: str | None
) -> dict[str, Any]:
    if profile_id:
        profile = await session.get(ModelProfile, profile_id)
        if profile:
            data = _profile_dict(profile)
            data["api_key"] = await _api_key(session, tenant_id, data)
            return data
    return {
        "id": None,
        "provider": "openai_compatible",
        "base_url": settings.default_embedding_base_url,
        "model": settings.default_embedding_model,
        "api_key": settings.default_embedding_api_key,
        "embedding_dimension": settings.default_embedding_dimension,
        "timeout_sec": 120,
    }


async def chat(
    profile: dict[str, Any],
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    response_format: dict[str, Any] | None = None,
) -> ChatResult:
    base_url = str(profile.get("base_url") or "").rstrip("/")
    if not base_url:
        raise ModelError("model profile has no base_url")
    url = base_url + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if profile.get("api_key"):
        headers["Authorization"] = f"Bearer {profile['api_key']}"
    payload: dict[str, Any] = {
        "model": profile["model"],
        "messages": messages,
        "temperature": profile.get("temperature", 0.2),
        "max_tokens": profile.get("max_tokens", 2048),
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    if response_format:
        payload["response_format"] = response_format
    timeout = httpx.Timeout(float(profile.get("timeout_sec", 120)))
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:2000]
        raise ModelError(f"model HTTP {exc.response.status_code}: {body}") from exc
    except httpx.HTTPError as exc:
        raise ModelError(f"model request failed: {exc}") from exc
    choices = data.get("choices") or []
    if not choices:
        raise ModelError("model returned no choices")
    message = choices[0].get("message") or {}
    content = message.get("content") or ""
    tool_calls = []
    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        arguments = function.get("arguments") or "{}"
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {"raw": arguments}
        tool_calls.append(
            {
                "id": call.get("id") or "",
                "name": function.get("name") or "",
                "arguments": arguments,
            }
        )
    usage = data.get("usage") or {}
    tokens = int(usage.get("total_tokens") or (usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)))
    return ChatResult(content=str(content), tool_calls=tool_calls, tokens=tokens, raw=data)


async def embed(profile: dict[str, Any], texts: list[str]) -> tuple[list[list[float]], int]:
    if not texts:
        return [], 0
    base_url = str(profile.get("base_url") or "").rstrip("/")
    if not base_url:
        raise ModelError("embedding profile has no base_url")
    url = base_url + "/embeddings"
    headers = {"Content-Type": "application/json"}
    if profile.get("api_key"):
        headers["Authorization"] = f"Bearer {profile['api_key']}"
    payload: dict[str, Any] = {"model": profile["model"], "input": texts}
    if profile.get("provider") != "ollama" and profile.get("embedding_dimension"):
        payload["dimensions"] = int(profile["embedding_dimension"])
    timeout = httpx.Timeout(float(profile.get("timeout_sec", 120)))
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:2000]
        raise ModelError(f"embedding HTTP {exc.response.status_code}: {body}") from exc
    except httpx.HTTPError as exc:
        raise ModelError(f"embedding request failed: {exc}") from exc
    items = sorted(data.get("data") or [], key=lambda item: item.get("index", 0))
    vectors = [item.get("embedding") or [] for item in items]
    usage = data.get("usage") or {}
    tokens = int(usage.get("total_tokens") or usage.get("prompt_tokens") or 0)
    if not vectors:
        raise ModelError("embedding response contained no vectors")
    return vectors, tokens

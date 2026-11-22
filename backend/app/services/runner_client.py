from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

import httpx

from app.config import settings


class RunnerError(Exception):
    pass


def sign_payload(body: bytes, timestamp: str) -> str:
    message = timestamp.encode() + b"." + body
    return hmac.new(settings.runner_hmac_secret.encode(), message, hashlib.sha256).hexdigest()


async def execute_code(
    source: str,
    input_data: dict[str, Any],
    *,
    timeout_sec: int | None = None,
    memory_mb: int | None = None,
) -> dict[str, Any]:
    payload = {
        "source": source,
        "input": input_data,
        "timeout_sec": timeout_sec or settings.runner_timeout_seconds,
        "memory_mb": memory_mb or settings.runner_memory_mb,
    }
    body = json.dumps(payload).encode()
    timestamp = str(int(time.time()))
    headers = {
        "Content-Type": "application/json",
        "X-Runner-Timestamp": timestamp,
        "X-Runner-Signature": sign_payload(body, timestamp),
    }
    try:
        async with httpx.AsyncClient(timeout=float((timeout_sec or settings.runner_timeout_seconds) + 10)) as client:
            response = await client.post(settings.runner_url.rstrip("/") + "/execute", content=body, headers=headers)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as exc:
        raise RunnerError(f"runner HTTP {exc.response.status_code}: {exc.response.text[:1000]}") from exc
    except httpx.HTTPError as exc:
        raise RunnerError(f"runner unavailable: {exc}") from exc

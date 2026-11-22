from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/v1/mcp/demo", tags=["mcp-demo"])

TOOLS: list[dict[str, Any]] = [
    {
        "name": "echo",
        "description": "原样返回传入的 message，适合验证 MCP 连接是否打通。",
        "inputSchema": {
            "type": "object",
            "properties": {"message": {"type": "string", "description": "要回显的文本"}},
            "required": ["message"],
        },
    },
    {
        "name": "add",
        "description": "计算两个数字之和。",
        "inputSchema": {
            "type": "object",
            "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
            "required": ["a", "b"],
        },
    },
    {
        "name": "server_time",
        "description": "返回 FlowMind 内置演示 MCP 服务的当前 UTC 时间。",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _text(value: Any) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": str(value)}], "structuredContent": {"result": value}}


@router.post("")
async def handle(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception:
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "invalid JSON"}}
    request_id = payload.get("id")
    method = str(payload.get("method") or "")
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "FlowMind Demo MCP", "version": "1.0.0"},
            },
        }
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = payload.get("params") or {}
        name = str(params.get("name") or "")
        arguments = params.get("arguments") or {}
        if name == "echo":
            message = str(arguments.get("message") or "")
            return {"jsonrpc": "2.0", "id": request_id, "result": _text(message)}
        if name == "add":
            try:
                value = float(arguments.get("a")) + float(arguments.get("b"))
            except (TypeError, ValueError):
                return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": "a and b must be numbers"}}
            return {"jsonrpc": "2.0", "id": request_id, "result": _text(value)}
        if name == "server_time":
            return {"jsonrpc": "2.0", "id": request_id, "result": _text(datetime.now(UTC).isoformat())}
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"unknown tool: {name}"}}
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"unknown method: {method}"}}
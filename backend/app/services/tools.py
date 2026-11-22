from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import McpServer, McpTool, OAuthConnection, Tool
from app.services import oauth, plugins, rag
from app.services.http_client import request_json
from app.services.secrets import resolve_secret_refs


class ToolError(Exception):
    pass


class ApprovalRequired(Exception):
    def __init__(
        self,
        *,
        title: str,
        description: str,
        tool_name: str,
        args: dict[str, Any],
        risk_level: str,
        agent_name: str | None = None,
        state: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(description or title)
        self.title = title
        self.description = description
        self.tool_name = tool_name
        self.arguments = args
        self.risk_level = risk_level
        self.agent_name = agent_name
        self.state = state or {}


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_")
    return cleaned[:64] or "tool"


@dataclass
class ToolInfo:
    id: str
    name: str
    description: str
    input_schema: dict[str, Any]
    risk_level: str
    type: str
    config: dict[str, Any] = field(default_factory=dict)
    builtin: bool = False


class ToolExecutor:
    def __init__(
        self,
        session: AsyncSession,
        tenant_id: str,
        *,
        tool_ids: list[str] | None = None,
        kb_ids: list[str] | None = None,
        approved_tools: set[str] | None = None,
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.tool_ids = tool_ids or []
        self.kb_ids = kb_ids or []
        self.approved_tools = approved_tools or set()
        self.tools: dict[str, ToolInfo] = {}
        self._loaded = False

    async def load(self) -> None:
        if self._loaded:
            return
        if self.tool_ids:
            result = await self.session.execute(
                select(Tool).where(
                    Tool.tenant_id == self.tenant_id,
                    Tool.id.in_(self.tool_ids),
                    Tool.enabled.is_(True),
                )
            )
            for tool in result.scalars().all():
                name = _safe_name(tool.name)
                self.tools[name] = ToolInfo(
                    id=tool.id,
                    name=name,
                    description=tool.description or tool.name,
                    input_schema=tool.input_schema or {"type": "object", "properties": {}},
                    risk_level=tool.risk_level,
                    type=tool.type,
                    config=tool.config or {},
                )
        if self.kb_ids:
            self.tools["knowledge_search"] = ToolInfo(
                id="builtin:knowledge_search",
                name="knowledge_search",
                description="Search the bound knowledge bases and return cited chunks.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "top_k": {"type": "integer", "default": 8},
                    },
                    "required": ["query"],
                },
                risk_level="low",
                type="builtin",
                builtin=True,
            )
        self._loaded = True

    async def schemas(self) -> list[dict[str, Any]]:
        await self.load()
        return [
            {
                "type": "function",
                "function": {
                    "name": info.name,
                    "description": info.description,
                    "parameters": info.input_schema,
                },
            }
            for info in self.tools.values()
        ]

    async def requires_approval(self, name: str) -> bool:
        await self.load()
        info = self.tools.get(name)
        if not info:
            return False
        return info.risk_level in {"medium", "high"} and name not in self.approved_tools

    async def call(self, name: str, args: dict[str, Any], *, approved: bool = False) -> dict[str, Any]:
        await self.load()
        info = self.tools.get(name)
        if not info:
            raise ToolError(f"tool '{name}' is not bound to this agent")
        if info.risk_level == "deny":
            raise ToolError(f"tool '{name}' is disabled by policy")
        if info.risk_level in {"medium", "high"} and not approved and name not in self.approved_tools:
            raise ApprovalRequired(
                title=f"Approve tool call: {name}",
                description=info.description,
                tool_name=name,
                args=args,
                risk_level=info.risk_level,
            )
        if info.builtin and name == "knowledge_search":
            response = await rag.search(
                self.session,
                tenant_id=self.tenant_id,
                kb_ids=self.kb_ids,
                query=str(args.get("query") or ""),
                top_k=int(args.get("top_k") or 8),
            )
            return response.model_dump()
        return await execute_registered_tool(
            self.session,
            tenant_id=self.tenant_id,
            tool=info,
            inputs=args,
        )


async def execute_registered_tool(
    session: AsyncSession, *, tenant_id: str, tool: ToolInfo, inputs: dict[str, Any]
) -> dict[str, Any]:
    config = await resolve_secret_refs(session, tenant_id, tool.config)
    if tool.type == "http":
        method = str(config.get("method") or "POST")
        url = str(config.get("url") or "")
        if not url:
            raise ToolError("http tool has no url")
        headers = dict(config.get("headers") or {})
        oauth_connection_id = config.get("oauth_connection_id")
        if oauth_connection_id:
            connection = await session.get(OAuthConnection, str(oauth_connection_id))
            if not connection or connection.tenant_id != tenant_id:
                raise ToolError("OAuth connection not found")
            before = (connection.access_token_ciphertext, connection.expires_at)
            try:
                token = await oauth.access_token(connection)
            except oauth.OAuthError as exc:
                raise ToolError(f"OAuth token unavailable: {exc}") from exc
            if (connection.access_token_ciphertext, connection.expires_at) != before:
                await session.commit()
            headers["Authorization"] = f"Bearer {token}"
        params = config.get("params") or {}
        body = inputs if config.get("body_mode", "json") == "json" else config.get("body")
        result = await request_json(
            method=method,
            url=url,
            headers=headers,
            params=params,
            body=body,
            timeout_sec=int(config.get("timeout_sec") or 30),
            allowed_domains=list(config.get("allowed_domains") or []),
        )
        return {"status_code": result.status_code, "body": result.body, "text": result.text[:4000]}
    if tool.type == "plugin":
        plugin_id = str(config.get("plugin_id") or "")
        if not plugin_id:
            raise ToolError("plugin tool has no plugin_id")
        try:
            return await plugins.execute_plugin(
                plugin_id,
                dict(config.get("plugin_config") or {}),
                inputs,
            )
        except Exception as exc:
            raise ToolError(str(exc)) from exc
    if tool.type == "mcp":
        server_id = str(config.get("server_id") or "")
        mcp_tool_name = str(config.get("tool_name") or tool.name)
        server = await session.get(McpServer, server_id)
        if not server:
            raise ToolError("mcp server not found")
        return await call_mcp_tool(session, tenant_id, server, mcp_tool_name, inputs)
    if tool.type == "subworkflow":
        raise ToolError("subworkflow tools must be executed by the workflow engine")
    raise ToolError(f"unsupported tool type: {tool.type}")


async def call_mcp_tool(
    session: AsyncSession,
    tenant_id: str,
    server: McpServer,
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    headers = dict(server.headers or {})
    headers.setdefault("Content-Type", "application/json")
    headers.setdefault("Accept", "application/json, text/event-stream")
    payload = {
        "jsonrpc": "2.0",
        "id": "flowmind-1",
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(server.url, headers=headers, json=payload)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if "text/event-stream" in content_type:
                data_lines = [
                    line[len("data:") :].strip()
                    for line in response.text.splitlines()
                    if line.startswith("data:")
                ]
                for line in data_lines:
                    if not line or line == "[DONE]":
                        continue
                    data = json.loads(line)
                    if "result" in data:
                        return data["result"]
                raise ToolError("MCP stream returned no result")
            data = response.json()
    except httpx.HTTPError as exc:
        raise ToolError(f"MCP request failed: {exc}") from exc
    if "error" in data:
        raise ToolError(f"MCP error: {data['error']}")
    return data.get("result") or {}


async def discover_mcp_tools(
    session: AsyncSession, tenant_id: str, server: McpServer
) -> list[McpTool]:
    headers = dict(server.headers or {})
    headers.setdefault("Content-Type", "application/json")
    headers.setdefault("Accept", "application/json, text/event-stream")
    payload = {"jsonrpc": "2.0", "id": "flowmind-discover", "method": "tools/list", "params": {}}
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(server.url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        raise ToolError(f"MCP discovery failed: {exc}") from exc
    tools = []
    for item in (data.get("result") or {}).get("tools") or []:
        name = str(item.get("name") or "")
        if not name:
            continue
        existing = await session.execute(
            select(McpTool).where(McpTool.server_id == server.id, McpTool.name == name)
        )
        tool = existing.scalar_one_or_none()
        if tool is None:
            tool = McpTool(tenant_id=tenant_id, server_id=server.id, name=name)
            session.add(tool)
        tool.description = str(item.get("description") or "")
        tool.input_schema = item.get("inputSchema") or {"type": "object", "properties": {}}
        tool.risk_level = "medium"
        tools.append(tool)
    await session.flush()
    return tools


from __future__ import annotations

import ast
import base64
import html
import json
import operator
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx
import jmespath

from app.services.http_client import request_json


@dataclass(frozen=True)
class PluginDefinition:
    id: str
    name: str
    description: str
    category: str
    vendor: str
    version: str
    icon: str
    permissions: list[str]
    risk_level: str
    input_schema: dict[str, Any]
    config_schema: list[dict[str, Any]]
    highlights: list[str]


CATALOG: list[PluginDefinition] = [
    PluginDefinition(
        id="calculator",
        name="计算器",
        description="安全计算数学表达式，适合在 Agent 中做价格、折扣、比例等快速核算。",
        category="效率工具",
        vendor="FlowMind",
        version="1.0.0",
        icon="calculator",
        permissions=["读取输入参数"],
        risk_level="low",
        input_schema={
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "例如 (1280 * 0.85) + 36"},
            },
            "required": ["expression"],
        },
        config_schema=[],
        highlights=["支持四则运算、括号与幂运算", "不执行函数调用或任意代码"],
    ),
    PluginDefinition(
        id="current_time",
        name="当前时间",
        description="获取指定时区的当前日期时间，适合在提示词和报表中补充时间上下文。",
        category="效率工具",
        vendor="FlowMind",
        version="1.0.0",
        icon="clock",
        permissions=["读取系统时间"],
        risk_level="low",
        input_schema={
            "type": "object",
            "properties": {"timezone": {"type": "string", "description": "例如 Asia/Shanghai，默认 UTC"}},
        },
        config_schema=[],
        highlights=["支持 IANA 时区", "返回 ISO 时间与日期"],
    ),
    PluginDefinition(
        id="text_stats",
        name="文本统计",
        description="统计字符数、单词数、行数与高频词，适合做内容审核和摘要前的预处理。",
        category="数据处理",
        vendor="FlowMind",
        version="1.0.0",
        icon="file-text",
        permissions=["读取输入参数"],
        risk_level="low",
        input_schema={
            "type": "object",
            "properties": {"text": {"type": "string", "description": "待统计的文本"}},
            "required": ["text"],
        },
        config_schema=[],
        highlights=["中英文均可统计", "返回高频词 Top 10"],
    ),
    PluginDefinition(
        id="json_extract",
        name="JSON 提取",
        description="使用 JMESPath 从结构化 JSON 中提取字段，适合处理 API 返回与工具输出。",
        category="数据处理",
        vendor="FlowMind",
        version="1.0.0",
        icon="braces",
        permissions=["读取输入参数"],
        risk_level="low",
        input_schema={
            "type": "object",
            "properties": {
                "data": {"type": "object", "description": "JSON 对象，或 JSON 字符串"},
                "expression": {"type": "string", "description": "JMESPath，例如 data.items[0].name"},
            },
            "required": ["data", "expression"],
        },
        config_schema=[],
        highlights=["JMESPath 标准语法", "支持数组索引与过滤"],
    ),
    PluginDefinition(
        id="regex_extract",
        name="正则提取",
        description="用正则从文本中提取邮箱、订单号、链接等结构化片段。",
        category="数据处理",
        vendor="FlowMind",
        version="1.0.0",
        icon="scan-text",
        permissions=["读取输入参数"],
        risk_level="low",
        input_schema={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "待匹配文本"},
                "pattern": {"type": "string", "description": "Python 正则表达式"},
            },
            "required": ["text", "pattern"],
        },
        config_schema=[],
        highlights=["返回全部匹配与数量", "最多返回 100 条"],
    ),
    PluginDefinition(
        id="base64_codec",
        name="Base64 编解码",
        description="对文本做 Base64 编码或解码，适合调试接口与处理凭据片段。",
        category="数据处理",
        vendor="FlowMind",
        version="1.0.0",
        icon="binary",
        permissions=["读取输入参数"],
        risk_level="low",
        input_schema={
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "action": {"type": "string", "enum": ["encode", "decode"], "default": "encode"},
            },
            "required": ["text"],
        },
        config_schema=[],
        highlights=["encode / decode 两种模式", "UTF-8 文本安全"],
    ),
    PluginDefinition(
        id="wikipedia_search",
        name="维基百科搜索",
        description="搜索维基百科条目并返回摘要，为 Agent 提供公开知识补充。",
        category="搜索能力",
        vendor="FlowMind",
        version="1.0.0",
        icon="search",
        permissions=["访问公网", "读取公开百科内容"],
        risk_level="low",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
                "language": {"type": "string", "default": "zh", "description": "语言代码，例如 zh、en"},
                "limit": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
        config_schema=[],
        highlights=["无需 API Key", "返回标题、摘要与链接"],
    ),
    PluginDefinition(
        id="http_request",
        name="HTTP 连接器",
        description="把任意 HTTP API 包装成 Agent 工具，支持配置基础 URL、请求方法和域名白名单。",
        category="集成连接",
        vendor="FlowMind",
        version="1.0.0",
        icon="globe",
        permissions=["访问公网", "发送外部请求"],
        risk_level="medium",
        input_schema={
            "type": "object",
            "properties": {
                "params": {"type": "object", "description": "查询参数"},
                "body": {"type": "object", "description": "JSON 请求体"},
            },
        },
        config_schema=[
            {"key": "base_url", "label": "基础 URL", "type": "url", "required": True, "placeholder": "https://api.example.com/v1/items", "hint": "工具会向这个地址发起请求。"},
            {"key": "method", "label": "请求方法", "type": "select", "required": True, "default": "POST", "options": ["GET", "POST", "PUT", "PATCH", "DELETE"]},
            {"key": "allowed_domains", "label": "域名白名单", "type": "text", "required": False, "placeholder": "api.example.com", "hint": "多个域名用逗号分隔；留空时只允许公网地址。"},
        ],
        highlights=["复用 HTTP 安全策略", "中风险调用会进入审批"],
    ),
    PluginDefinition(
        id="webhook_notify",
        name="Webhook 通知",
        description="向指定 Webhook 地址发送消息，适合把工作流结果推送到 IM 或自建服务。",
        category="通讯协作",
        vendor="FlowMind",
        version="1.0.0",
        icon="send",
        permissions=["对外发送消息", "访问公网"],
        risk_level="medium",
        input_schema={
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "通知正文"},
                "payload": {"type": "object", "description": "额外结构化字段"},
            },
            "required": ["message"],
        },
        config_schema=[
            {"key": "webhook_url", "label": "Webhook URL", "type": "url", "required": True, "placeholder": "https://hooks.example.com/flowmind", "hint": "请先在目标平台创建 Webhook。"},
            {"key": "allowed_domains", "label": "域名白名单", "type": "text", "required": False, "placeholder": "hooks.example.com"},
        ],
        highlights=["支持附加 JSON 字段", "中风险调用会进入审批"],
    ),
]

_BY_ID = {item.id: item for item in CATALOG}


def get_plugin(plugin_id: str) -> PluginDefinition | None:
    return _BY_ID.get(plugin_id)


def definition_dict(definition: PluginDefinition) -> dict[str, Any]:
    return asdict(definition)


def validate_config(definition: PluginDefinition, config: dict[str, Any] | None) -> dict[str, Any]:
    config = dict(config or {})
    for field in definition.config_schema:
        if field.get("required"):
            value = config.get(field["key"])
            if value is None or (isinstance(value, str) and not value.strip()):
                raise ValueError(f"{field.get('label') or field['key']} 必填")
    return config


_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}


def _eval_math(node: ast.AST) -> float | int:
    if isinstance(node, ast.Expression):
        return _eval_math(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        left = _eval_math(node.left)
        right = _eval_math(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 100:
            raise ValueError("指数过大")
        return _BIN_OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _eval_math(node.operand)
        return value if isinstance(node.op, ast.UAdd) else -value
    raise ValueError("表达式只支持数字、括号和四则运算")


def safe_calculate(expression: str) -> float | int:
    expression = expression.strip()
    if not expression or len(expression) > 500:
        raise ValueError("表达式为空或过长")
    return _eval_math(ast.parse(expression, mode="eval"))


async def _wikipedia_search(inputs: dict[str, Any]) -> dict[str, Any]:
    query = str(inputs.get("query") or "").strip()
    if not query:
        raise ValueError("query 必填")
    language = str(inputs.get("language") or "zh").strip().lower()
    if not re.fullmatch(r"[a-z-]{2,12}", language):
        raise ValueError("language 不合法")
    limit = max(1, min(10, int(inputs.get("limit") or 5)))
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        response = await client.get(
            f"https://{language}.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srlimit": limit,
                "format": "json",
                "utf8": 1,
            },
            headers={"User-Agent": "FlowMind/0.1 (plugin: wikipedia_search)"},
        )
        response.raise_for_status()
        payload = response.json()
    results = []
    for item in (payload.get("query", {}).get("search") or [])[:limit]:
        snippet = re.sub(r"<[^>]+>", "", str(item.get("snippet") or ""))
        title = str(item.get("title") or "")
        results.append(
            {
                "title": title,
                "snippet": html.unescape(snippet),
                "page_id": item.get("pageid"),
                "url": f"https://{language}.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}",
            }
        )
    return {"query": query, "language": language, "results": results}


async def execute_plugin(plugin_id: str, config: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    definition = get_plugin(plugin_id)
    if not definition:
        raise ValueError(f"plugin not found: {plugin_id}")
    inputs = dict(inputs or {})

    if plugin_id == "calculator":
        value = safe_calculate(str(inputs.get("expression") or ""))
        return {"result": value, "expression": inputs.get("expression")}

    if plugin_id == "current_time":
        timezone_name = str(inputs.get("timezone") or config.get("timezone") or "UTC")
        try:
            tz = ZoneInfo(timezone_name)
        except Exception:
            tz = UTC
        now = datetime.now(tz)
        return {
            "timezone": timezone_name if tz is not UTC else "UTC",
            "iso": now.isoformat(),
            "date": now.date().isoformat(),
            "time": now.strftime("%H:%M:%S"),
        }

    if plugin_id == "text_stats":
        text = str(inputs.get("text") or "")
        words = re.findall(r"[\w\u4e00-\u9fff]+", text.lower())
        counts: dict[str, int] = {}
        for word in words:
            counts[word] = counts.get(word, 0) + 1
        top = sorted(counts.items(), key=lambda item: item[1], reverse=True)[:10]
        return {
            "characters": len(text),
            "characters_no_spaces": len(re.sub(r"\s", "", text)),
            "words": len(words),
            "lines": len(text.splitlines()) if text else 0,
            "top_words": [{"word": word, "count": count} for word, count in top],
        }

    if plugin_id == "json_extract":
        data = inputs.get("data")
        if isinstance(data, str):
            data = json.loads(data)
        expression = str(inputs.get("expression") or "").strip()
        if not expression:
            raise ValueError("expression 必填")
        return {"result": jmespath.search(expression, data), "expression": expression}

    if plugin_id == "regex_extract":
        text = str(inputs.get("text") or "")
        pattern = str(inputs.get("pattern") or "")
        if not pattern:
            raise ValueError("pattern 必填")
        matches = [str(item) for item in re.findall(pattern, text)[:100]]
        return {"count": len(matches), "matches": matches}

    if plugin_id == "base64_codec":
        text = str(inputs.get("text") or "")
        action = str(inputs.get("action") or "encode")
        if action == "decode":
            return {"result": base64.b64decode(text).decode("utf-8")}
        return {"result": base64.b64encode(text.encode("utf-8")).decode("ascii")}

    if plugin_id == "wikipedia_search":
        return await _wikipedia_search(inputs)

    if plugin_id == "http_request":
        base_url = str(config.get("base_url") or "").strip()
        if not base_url:
            raise ValueError("请先配置基础 URL")
        method = str(config.get("method") or "POST").upper()
        allowed = [part.strip() for part in str(config.get("allowed_domains") or "").split(",") if part.strip()]
        result = await request_json(
            method=method,
            url=base_url,
            params=inputs.get("params") if isinstance(inputs.get("params"), dict) else None,
            body=inputs.get("body"),
            allowed_domains=allowed,
            timeout_sec=30,
        )
        return {"status_code": result.status_code, "body": result.body, "text": result.text[:4000]}

    if plugin_id == "webhook_notify":
        webhook_url = str(config.get("webhook_url") or "").strip()
        if not webhook_url:
            raise ValueError("请先配置 Webhook URL")
        allowed = [part.strip() for part in str(config.get("allowed_domains") or "").split(",") if part.strip()]
        payload = inputs.get("payload") if isinstance(inputs.get("payload"), dict) else {}
        body = {"message": str(inputs.get("message") or ""), **payload}
        result = await request_json(
            method="POST",
            url=webhook_url,
            body=body,
            allowed_domains=allowed,
            timeout_sec=30,
        )
        return {"status_code": result.status_code, "body": result.body, "text": result.text[:4000]}

    raise ValueError(f"unsupported plugin: {plugin_id}")
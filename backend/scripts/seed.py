from __future__ import annotations

import asyncio
import hashlib
import json
import secrets

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal, init_db
from app.models import (
    AgentProfile,
    KnowledgeBase,
    McpServer,
    Membership,
    ModelProfile,
    PluginInstallation,
    Tenant,
    Tool,
    User,
    WebhookEndpoint,
    Workflow,
    WorkflowVersion,
)
from app.security import hash_password
from app.services import plugins as plugin_service
from app.services import workflow_templates


def dsl(nodes: list[dict], edges: list[dict], inputs: dict | None = None) -> dict:
    return {
        "schema_version": "1.0",
        "inputs": inputs or {"type": "object", "properties": {}},
        "nodes": nodes,
        "edges": edges,
        "settings": {"timeout_sec": 1800, "max_parallel": 4, "on_error": "fail"},
    }


async def seed(init: bool = True) -> None:
    if init:
        await init_db()
    async with SessionLocal() as session:
        existing = await session.execute(select(User).where(User.email == "demo@flowmind.dev"))
        user = existing.scalar_one_or_none()
        if user:
            print("Demo data already exists: demo@flowmind.dev / password123")
            return
        user = User(
            email="demo@flowmind.dev",
            name="Demo Owner",
            password_hash=hash_password("password123"),
            email_verified=True,
        )
        session.add(user)
        await session.flush()
        tenant = Tenant(name="FlowMind Demo", slug="flowmind-demo", created_by=user.id, settings={})
        session.add(tenant)
        await session.flush()
        session.add(Membership(tenant_id=tenant.id, user_id=user.id, role="owner"))
        model = ModelProfile(
            tenant_id=tenant.id,
            name="Local Ollama",
            provider="ollama",
            base_url=settings.default_chat_base_url,
            model=settings.default_chat_model,
            embedding_dimension=settings.default_embedding_dimension,
            max_tokens=2048,
            temperature=0.2,
            timeout_sec=120,
            is_default=True,
        )
        session.add(model)
        await session.flush()
        tool = Tool(
            tenant_id=tenant.id,
            name="httpbin_json",
            type="http",
            description="获取 httpbin 的示例 JSON 数据。",
            input_schema={"type": "object", "properties": {}},
            config={"method": "GET", "url": "https://httpbin.org/json", "timeout_sec": 30},
            risk_level="low",
            enabled=True,
        )
        session.add(tool)
        await session.flush()
        plugin_tool_ids: list[str] = []
        for plugin_id in ("calculator", "current_time"):
            definition = plugin_service.get_plugin(plugin_id)
            if not definition:
                continue
            plugin_tool = Tool(
                tenant_id=tenant.id,
                name=definition.id,
                type="plugin",
                description=definition.description,
                input_schema=definition.input_schema,
                config={"plugin_id": definition.id, "plugin_config": {}},
                risk_level=definition.risk_level,
                enabled=True,
            )
            session.add(plugin_tool)
            await session.flush()
            session.add(
                PluginInstallation(
                    tenant_id=tenant.id,
                    plugin_id=definition.id,
                    version=definition.version,
                    config={},
                    status="installed",
                    tool_id=plugin_tool.id,
                    installed_by=user.id,
                )
            )
            plugin_tool_ids.append(plugin_tool.id)
        kb = KnowledgeBase(
            tenant_id=tenant.id,
            name="产品资料",
            description="上传产品手册、FAQ 或价格表后即可搜索。",
            embedding_model_profile_id=None,
            chunk_size=800,
            chunk_overlap=100,
            created_by=user.id,
        )
        session.add(kb)
        await session.flush()
        researcher = AgentProfile(
            tenant_id=tenant.id,
            name="研究员",
            role_prompt=(
                "你是一个严谨的研究助手。请使用绑定的知识库和工具；"
                "引用检索内容时保留来源分块 ID。"
            ),
            model_profile_id=None,
            tool_ids=[tool.id, *plugin_tool_ids],
            kb_ids=[kb.id],
            max_iterations=8,
            output_schema={"type": "object", "properties": {"answer": {"type": "string"}, "citations": {"type": "array"}}},
            temperature=0.2,
        )
        writer = AgentProfile(
            tenant_id=tenant.id,
            name="编辑",
            role_prompt="你负责把研究结果整理成简洁、准确的中文简报。",
            model_profile_id=None,
            tool_ids=[],
            kb_ids=[kb.id],
            max_iterations=6,
            output_schema={"type": "object", "properties": {"briefing": {"type": "string"}}},
            temperature=0.3,
        )
        session.add_all([researcher, writer])
        await session.flush()

        workflows = [
            {
                "name": "知识库问答",
                "description": "检索绑定知识库并生成带引用的回答。",
                "dsl": dsl(
                    [
                        {"id": "start", "type": "start", "name": "开始", "config": {}, "position": {"x": 80, "y": 160}},
                        {"id": "search", "type": "tool", "name": "检索知识库", "config": {"tool_id": "knowledge_search", "kb_ids": [kb.id], "input": {"query": "{{ inputs.question }}", "top_k": 6}}, "position": {"x": 300, "y": 160}},
                        {"id": "answer", "type": "agent", "name": "生成回答", "config": {"agent_profile_id": researcher.id, "goal": "请回答用户问题：{{ inputs.question }}\n检索上下文：{{ nodes.search }}"}, "position": {"x": 540, "y": 160}},
                        {"id": "end", "type": "end", "name": "结束", "config": {"outputs": {"answer": "{{ nodes.answer }}"}}, "position": {"x": 800, "y": 160}},
                    ],
                    [
                        {"id": "e1", "source": "start", "target": "search"},
                        {"id": "e2", "source": "search", "target": "answer"},
                        {"id": "e3", "source": "answer", "target": "end"},
                    ],
                    inputs={"type": "object", "properties": {"question": {"type": "string", "title": "Question", "default": "What is the refund policy?"}}, "required": ["question"]},
                ),
            },
            {
                "name": "每日简报",
                "description": "抓取 JSON 数据，生成中文简报，并在发布前人工确认。",
                "dsl": dsl(
                    [
                        {"id": "start", "type": "start", "name": "开始", "config": {}, "position": {"x": 80, "y": 160}},
                        {"id": "fetch", "type": "http", "name": "获取数据", "config": {"method": "GET", "url": "https://httpbin.org/json"}, "position": {"x": 300, "y": 160}},
                        {"id": "brief", "type": "llm", "name": "生成简报", "config": {"model_profile_id": "", "prompt": "请把以下数据整理成 3 条中文要点：\n{{ nodes.fetch.body }}"}, "position": {"x": 540, "y": 160}},
                        {"id": "approve", "type": "approval", "name": "人工确认", "config": {"title": "确认今日简报", "description": "发布前请核对简报内容。"}, "position": {"x": 780, "y": 160}},
                        {"id": "end", "type": "end", "name": "结束", "config": {"outputs": {"briefing": "{{ nodes.brief.text }}"}}, "position": {"x": 1000, "y": 160}},
                    ],
                    [
                        {"id": "e1", "source": "start", "target": "fetch"},
                        {"id": "e2", "source": "fetch", "target": "brief"},
                        {"id": "e3", "source": "brief", "target": "approve"},
                        {"id": "e4", "source": "approve", "target": "end"},
                    ],
                ),
            },
            {
                "name": "多智能体研究",
                "description": "主管 Agent 协调研究员与编辑，输出最终简报。",
                "dsl": dsl(
                    [
                        {"id": "start", "type": "start", "name": "开始", "config": {}, "position": {"x": 80, "y": 160}},
                        {"id": "team", "type": "agent_team", "name": "研究团队", "config": {"mode": "supervisor", "supervisor_profile_id": researcher.id, "worker_profile_ids": [researcher.id, writer.id], "max_handoffs": 8, "max_steps": 12, "token_budget": 60000, "goal": "请研究并撰写关于以下主题的简报：{{ inputs.topic }}"}, "position": {"x": 340, "y": 160}},
                        {"id": "end", "type": "end", "name": "结束", "config": {"outputs": {"result": "{{ nodes.team }}"}}, "position": {"x": 640, "y": 160}},
                    ],
                    [
                        {"id": "e1", "source": "start", "target": "team"},
                        {"id": "e2", "source": "team", "target": "end"},
                    ],
                    inputs={"type": "object", "properties": {"topic": {"type": "string", "title": "Topic", "default": "AI Agent workflow platform"}}, "required": ["topic"]},
                ),
            },
        ]

        for template_id in ("webhook_receiver", "http_fetch", "llm_summary", "approval_flow", "scheduled_brief"):
            template = workflow_templates.get_template(template_id)
            if template:
                template_dsl = json.loads(json.dumps(template.dsl, ensure_ascii=False))
                for node in template_dsl.get("nodes") or []:
                    config = node.setdefault("config", {})
                    if node.get("type") == "llm" and not config.get("model_profile_id"):
                        config["model_profile_id"] = model.id
                    if node.get("type") == "agent" and not config.get("agent_profile_id"):
                        config["agent_profile_id"] = researcher.id
                    if node.get("type") == "agent_team":
                        if not config.get("supervisor_profile_id"):
                            config["supervisor_profile_id"] = researcher.id
                        if not config.get("worker_profile_ids"):
                            config["worker_profile_ids"] = [researcher.id, writer.id]
                workflows.append({"name": template.name, "description": template.description, "dsl": template_dsl})

        workflow_by_name: dict[str, Workflow] = {}
        for item in workflows:
            workflow = Workflow(
                tenant_id=tenant.id,
                name=item["name"],
                description=item["description"],
                draft_dsl=item["dsl"],
                created_by=user.id,
            )
            session.add(workflow)
            await session.flush()
            canonical = json.dumps(item["dsl"], sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            version = WorkflowVersion(
                tenant_id=tenant.id,
                workflow_id=workflow.id,
                version=1,
                dsl=item["dsl"],
                dsl_hash=hashlib.sha256(canonical.encode()).hexdigest(),
                published_by=user.id,
            )
            session.add(version)
            await session.flush()
            workflow.version_no = 1
            workflow.current_version_id = version.id
            workflow_by_name[workflow.name] = workflow

        webhook_workflow = workflow_by_name.get("Webhook 接收示例")
        if webhook_workflow:
            session.add(
                WebhookEndpoint(
                    tenant_id=tenant.id,
                    workflow_id=webhook_workflow.id,
                    name="演示 Webhook（免签名）",
                    token="wh_" + secrets.token_urlsafe(32),
                    hmac_secret="",
                    enabled=True,
                )
            )
        session.add(
            McpServer(
                tenant_id=tenant.id,
                name="内置演示 MCP",
                transport="streamable_http",
                url=f"{settings.public_base_url.rstrip('/')}/api/v1/mcp/demo",
                headers={},
                enabled=True,
            )
        )

        await session.commit()
        print("Seed complete")
        print("Login: demo@flowmind.dev / password123")
        print(f"Tenant: {tenant.id}")
        print(f"Workflows: {len(workflows)} seeded, including Webhook receiver, HTTP fetch, LLM summary, approval flow")


if __name__ == "__main__":
    asyncio.run(seed())

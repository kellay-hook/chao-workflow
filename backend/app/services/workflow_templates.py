from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _dsl(nodes: list[dict[str, Any]], edges: list[dict[str, Any]], inputs: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "inputs": inputs or {"type": "object", "properties": {}},
        "nodes": nodes,
        "edges": edges,
        "settings": {"timeout_sec": 1800, "max_parallel": 4, "on_error": "fail"},
    }


def _start(x: int = 80, y: int = 160) -> dict[str, Any]:
    return {"id": "start", "type": "start", "name": "开始", "config": {}, "position": {"x": x, "y": y}}


def _end(outputs: dict[str, Any], x: int = 900, y: int = 160) -> dict[str, Any]:
    return {"id": "end", "type": "end", "name": "结束", "config": {"outputs": outputs}, "position": {"x": x, "y": y}}


@dataclass(frozen=True)
class WorkflowTemplate:
    id: str
    name: str
    description: str
    category: str
    trigger: str
    icon: str
    highlights: tuple[str, ...]
    dsl: dict[str, Any]

    def summary(self) -> dict[str, Any]:
        nodes = self.dsl.get("nodes") or []
        inputs = (self.dsl.get("inputs") or {}).get("properties") or {}
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "trigger": self.trigger,
            "icon": self.icon,
            "highlights": list(self.highlights),
            "node_count": len(nodes),
            "input_count": len(inputs),
            "preview_nodes": [
                {"type": str(node.get("type") or ""), "name": str(node.get("name") or node.get("type") or "")}
                for node in nodes
            ],
        }


WORKFLOW_TEMPLATES: list[WorkflowTemplate] = [
    WorkflowTemplate(
        id="webhook_receiver",
        name="Webhook 接收示例",
        description="接收外部系统的 JSON 事件，并在运行详情里查看原始 payload。无需模型，适合第一次理解 Webhook。",
        category="入门",
        trigger="Webhook",
        icon="webhook",
        highlights=("无需模型与密钥", "发布后即可获得 Webhook URL", "可直接发送测试事件"),
        dsl=_dsl(
            [
                _start(),
                _end(
                    {
                        "message": "Webhook 已成功触发",
                        "received": "{{ inputs.webhook }}",
                    },
                    x=520,
                ),
            ],
            [{"id": "e1", "source": "start", "target": "end", "source_port": "default", "target_port": "default"}],
        ),
    ),
    WorkflowTemplate(
        id="http_fetch",
        name="HTTP 数据抓取",
        description="调用一个公开 HTTP 接口，把返回的 JSON 作为工作流输出。适合理解 HTTP 节点与数据传递。",
        category="集成",
        trigger="手动",
        icon="globe",
        highlights=("使用 httpbin 公开接口", "演示节点输出引用", "无需模型即可运行"),
        dsl=_dsl(
            [
                _start(),
                {"id": "fetch", "type": "http", "name": "获取 JSON", "config": {"method": "GET", "url": "https://httpbin.org/json"}, "position": {"x": 320, "y": 160}},
                _end({"data": "{{ nodes.fetch.body }}"}, x=580),
            ],
            [
                {"id": "e1", "source": "start", "target": "fetch", "source_port": "default", "target_port": "default"},
                {"id": "e2", "source": "fetch", "target": "end", "source_port": "default", "target_port": "default"},
            ],
        ),
    ),
    WorkflowTemplate(
        id="llm_summary",
        name="LLM 文本总结",
        description="输入一段长文本，让默认 Chat 模型输出中文要点总结。适合快速验证模型配置。",
        category="AI",
        trigger="手动",
        icon="sparkles",
        highlights=("自动使用默认 Chat 模型", "输入一段文本即可运行", "输出结构化摘要"),
        dsl=_dsl(
            [
                _start(),
                {
                    "id": "summary",
                    "type": "llm",
                    "name": "生成摘要",
                    "config": {
                        "model_profile_id": "",
                        "prompt": "请用简洁的中文要点总结以下内容，保留关键数字与结论：\n\n{{ inputs.text }}",
                        "response_format": "text",
                    },
                    "position": {"x": 320, "y": 160},
                },
                _end({"summary": "{{ nodes.summary.text }}"}, x=620),
            ],
            [
                {"id": "e1", "source": "start", "target": "summary", "source_port": "default", "target_port": "default"},
                {"id": "e2", "source": "summary", "target": "end", "source_port": "default", "target_port": "default"},
            ],
            inputs={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "title": "待总结文本",
                        "description": "粘贴一段新闻、会议记录或产品说明。",
                        "default": "FlowMind 是一个自托管的工作流与 Agent 平台，支持知识库、工具调用与人工审批。",
                    }
                },
                "required": ["text"],
            },
        ),
    ),
    WorkflowTemplate(
        id="approval_flow",
        name="人工审批示例",
        description="先生成处理建议，再暂停等待人工审批，批准后输出最终结果。适合理解审批中断与恢复。",
        category="AI",
        trigger="手动",
        icon="shield",
        highlights=("包含 LLM 与审批节点", "审批后自动继续运行", "可在审批中心处理"),
        dsl=_dsl(
            [
                _start(),
                {
                    "id": "draft",
                    "type": "llm",
                    "name": "生成处理建议",
                    "config": {
                        "model_profile_id": "",
                        "prompt": "你是运营助手。请针对以下请求生成一段可执行的处理建议：\n{{ inputs.request }}",
                        "response_format": "text",
                    },
                    "position": {"x": 300, "y": 160},
                },
                {
                    "id": "approve",
                    "type": "approval",
                    "name": "人工确认",
                    "config": {"title": "确认处理建议", "description": "请核对模型生成的内容，批准后继续。", "risk_level": "medium"},
                    "position": {"x": 560, "y": 160},
                },
                _end({"result": "{{ nodes.draft.text }}", "approved": "{{ nodes.approve.approved }}"}, x=820),
            ],
            [
                {"id": "e1", "source": "start", "target": "draft", "source_port": "default", "target_port": "default"},
                {"id": "e2", "source": "draft", "target": "approve", "source_port": "default", "target_port": "default"},
                {"id": "e3", "source": "approve", "target": "end", "source_port": "default", "target_port": "default"},
            ],
            inputs={
                "type": "object",
                "properties": {
                    "request": {
                        "type": "string",
                        "title": "处理请求",
                        "default": "客户希望把订单 A1001 的收货地址改到公司前台。",
                    }
                },
                "required": ["request"],
            },
        ),
    ),
    WorkflowTemplate(
        id="scheduled_brief",
        name="定时数据简报",
        description="抓取公开数据并生成中文简报，适合作为定时任务的起点。创建后可在画布中配置定时触发。",
        category="集成",
        trigger="手动 / 定时",
        icon="clock",
        highlights=("HTTP + LLM 组合", "可配置 Cron 定时", "输出可直接推送"),
        dsl=_dsl(
            [
                _start(),
                {"id": "fetch", "type": "http", "name": "获取数据", "config": {"method": "GET", "url": "https://httpbin.org/json"}, "position": {"x": 300, "y": 160}},
                {
                    "id": "brief",
                    "type": "llm",
                    "name": "生成简报",
                    "config": {
                        "model_profile_id": "",
                        "prompt": "请把以下 JSON 数据整理成 3 条中文简报：\n{{ nodes.fetch.body }}",
                        "response_format": "text",
                    },
                    "position": {"x": 540, "y": 160},
                },
                _end({"briefing": "{{ nodes.brief.text }}"}, x=800),
            ],
            [
                {"id": "e1", "source": "start", "target": "fetch", "source_port": "default", "target_port": "default"},
                {"id": "e2", "source": "fetch", "target": "brief", "source_port": "default", "target_port": "default"},
                {"id": "e3", "source": "brief", "target": "end", "source_port": "default", "target_port": "default"},
            ],
        ),
    ),
    WorkflowTemplate(
        id="ticket_triage",
        name="客服工单智能分诊",
        description="识别工单类型与优先级，生成处理建议，人工确认后输出正式回复。适合客服、售后与工单中心。",
        category="复杂流程",
        trigger="手动 / Webhook",
        icon="shield",
        highlights=("LLM 分类 + 处理建议 + 人工确认", "支持从 Webhook 接入工单事件", "输出可直接回填工单系统"),
        dsl=_dsl(
            [
                _start(),
                {
                    "id": "classify",
                    "type": "llm",
                    "name": "识别工单类型",
                    "config": {
                        "model_profile_id": "",
                        "prompt": "你是客服分诊助手。请判断以下工单的类型、优先级和建议处理部门，用简洁中文输出：\n{{ inputs.ticket_text }}",
                        "response_format": "text",
                    },
                    "position": {"x": 280, "y": 160},
                },
                {
                    "id": "approve",
                    "type": "approval",
                    "name": "确认分诊方案",
                    "config": {"title": "确认工单分诊结果", "description": "请核对分类与建议，批准后生成正式回复。", "risk_level": "medium"},
                    "position": {"x": 540, "y": 160},
                },
                {
                    "id": "reply",
                    "type": "llm",
                    "name": "生成客服回复",
                    "config": {
                        "model_profile_id": "",
                        "prompt": "根据分诊结果生成一段专业、礼貌的中文客服回复。\n工单：{{ inputs.ticket_text }}\n分诊：{{ nodes.classify.text }}",
                        "response_format": "text",
                    },
                    "position": {"x": 800, "y": 160},
                },
                _end({"reply": "{{ nodes.reply.text }}", "triage": "{{ nodes.classify.text }}"}, x=1060),
            ],
            [
                {"id": "e1", "source": "start", "target": "classify", "source_port": "default", "target_port": "default"},
                {"id": "e2", "source": "classify", "target": "approve", "source_port": "default", "target_port": "default"},
                {"id": "e3", "source": "approve", "target": "reply", "source_port": "default", "target_port": "default"},
                {"id": "e4", "source": "reply", "target": "end", "source_port": "default", "target_port": "default"},
            ],
            inputs={
                "type": "object",
                "properties": {"ticket_text": {"type": "string", "title": "工单内容", "default": "客户反馈：订单 A1001 已付款但一直显示未发货，希望今天给出明确答复。"}},
                "required": ["ticket_text"],
            },
        ),
    ),
    WorkflowTemplate(
        id="content_pipeline",
        name="内容创作与审核发布",
        description="先写初稿，再由审稿模型提出修改意见，人工确认后调用 HTTP 发布接口。适合内容团队。",
        category="复杂流程",
        trigger="手动",
        icon="sparkles",
        highlights=("初稿 + 审稿双模型", "人工确认后调用发布接口", "输出发布结果与审稿意见"),
        dsl=_dsl(
            [
                _start(),
                {"id": "draft", "type": "llm", "name": "生成初稿", "config": {"model_profile_id": "", "prompt": "请围绕以下主题写一篇 300 字左右的中文内容初稿：\n{{ inputs.topic }}", "response_format": "text"}, "position": {"x": 260, "y": 160}},
                {"id": "review", "type": "llm", "name": "审稿与润色", "config": {"model_profile_id": "", "prompt": "请审阅并润色以下初稿，指出风险并输出最终版本：\n{{ nodes.draft.text }}", "response_format": "text"}, "position": {"x": 520, "y": 160}},
                {"id": "approve", "type": "approval", "name": "人工确认发布", "config": {"title": "确认发布内容", "description": "请核对最终文案，批准后调用发布接口。", "risk_level": "medium"}, "position": {"x": 780, "y": 160}},
                {"id": "publish", "type": "http", "name": "调用发布接口", "config": {"method": "POST", "url": "https://httpbin.org/post", "risk_level": "low", "body": {"topic": "{{ inputs.topic }}", "content": "{{ nodes.review.text }}"}}, "position": {"x": 1040, "y": 160}},
                _end({"published": "{{ nodes.publish.body }}", "final_content": "{{ nodes.review.text }}"}, x=1300),
            ],
            [
                {"id": "e1", "source": "start", "target": "draft", "source_port": "default", "target_port": "default"},
                {"id": "e2", "source": "draft", "target": "review", "source_port": "default", "target_port": "default"},
                {"id": "e3", "source": "review", "target": "approve", "source_port": "default", "target_port": "default"},
                {"id": "e4", "source": "approve", "target": "publish", "source_port": "default", "target_port": "default"},
                {"id": "e5", "source": "publish", "target": "end", "source_port": "default", "target_port": "default"},
            ],
            inputs={"type": "object", "properties": {"topic": {"type": "string", "title": "内容主题", "default": "FlowMind 如何帮助团队落地 AI 自动化"}}, "required": ["topic"]},
        ),
    ),
    WorkflowTemplate(
        id="ops_brief",
        name="运营数据双阶段分析",
        description="抓取运营数据，先用分析模型提取关键指标，再用格式化模型生成管理层简报。适合定时运营场景。",
        category="复杂流程",
        trigger="手动 / 定时",
        icon="clock",
        highlights=("HTTP 抓取 + 两阶段 LLM", "输出指标与最终简报", "可继续配置 Cron 定时"),
        dsl=_dsl(
            [
                _start(),
                {"id": "fetch", "type": "http", "name": "抓取运营数据", "config": {"method": "GET", "url": "https://httpbin.org/json"}, "position": {"x": 260, "y": 160}},
                {"id": "analyze", "type": "llm", "name": "提取关键指标", "config": {"model_profile_id": "", "prompt": "请从以下数据中提取 3-5 个最重要的运营指标，并说明变化趋势：\n{{ nodes.fetch.body }}", "response_format": "text"}, "position": {"x": 520, "y": 160}},
                {"id": "format", "type": "llm", "name": "生成管理层简报", "config": {"model_profile_id": "", "prompt": "请把以下指标分析整理成 3 条中文管理层简报，并给出下一步建议：\n{{ nodes.analyze.text }}", "response_format": "text"}, "position": {"x": 780, "y": 160}},
                _end({"briefing": "{{ nodes.format.text }}", "metrics": "{{ nodes.analyze.text }}"}, x=1040),
            ],
            [
                {"id": "e1", "source": "start", "target": "fetch", "source_port": "default", "target_port": "default"},
                {"id": "e2", "source": "fetch", "target": "analyze", "source_port": "default", "target_port": "default"},
                {"id": "e3", "source": "analyze", "target": "format", "source_port": "default", "target_port": "default"},
                {"id": "e4", "source": "format", "target": "end", "source_port": "default", "target_port": "default"},
            ],
        ),
    ),
    WorkflowTemplate(
        id="multi_agent_deep_research",
        name="多智能体深度研究",
        description="主管 Agent 协调多个成员完成研究，再由总结模型输出结构化报告。创建时会自动绑定当前租户的 Agent。",
        category="复杂流程",
        trigger="手动",
        icon="sparkles",
        highlights=("主管 + 多成员协作", "自动绑定现有 Agent", "最终输出结构化研究报告"),
        dsl=_dsl(
            [
                _start(),
                {"id": "team", "type": "agent_team", "name": "研究团队", "config": {"mode": "supervisor", "supervisor_profile_id": "", "worker_profile_ids": [], "max_handoffs": 8, "max_steps": 16, "token_budget": 80000, "goal": "围绕以下主题完成资料研究、观点对比与结论汇总：{{ inputs.topic }}"}, "position": {"x": 280, "y": 160}},
                {"id": "synth", "type": "llm", "name": "生成研究报告", "config": {"model_profile_id": "", "prompt": "请把多智能体研究结果整理成结构化中文报告，包含结论、依据和风险提示：\n{{ nodes.team }}", "response_format": "text"}, "position": {"x": 560, "y": 160}},
                _end({"report": "{{ nodes.synth.text }}", "team_result": "{{ nodes.team }}"}, x=840),
            ],
            [
                {"id": "e1", "source": "start", "target": "team", "source_port": "default", "target_port": "default"},
                {"id": "e2", "source": "team", "target": "synth", "source_port": "default", "target_port": "default"},
                {"id": "e3", "source": "synth", "target": "end", "source_port": "default", "target_port": "default"},
            ],
            inputs={"type": "object", "properties": {"topic": {"type": "string", "title": "研究主题", "default": "企业如何选择适合自己的 AI Agent 平台"}}, "required": ["topic"]},
        ),
    ),
    WorkflowTemplate(
        id="order_webhook_processing",
        name="Webhook 订单自动处理",
        description="接收外部订单事件，提取订单信息，人工确认后调用通知接口并输出处理回执。适合订单、审批与履约场景。",
        category="复杂流程",
        trigger="Webhook / 手动",
        icon="webhook",
        highlights=("Webhook + LLM 提取 + 审批", "调用外部通知接口", "输出结构化处理回执"),
        dsl=_dsl(
            [
                _start(),
                {"id": "extract", "type": "llm", "name": "提取订单信息", "config": {"model_profile_id": "", "prompt": "请从以下 Webhook 事件中提取订单号、金额、客户和风险点：\n{{ inputs.webhook }}", "response_format": "text"}, "position": {"x": 260, "y": 160}},
                {"id": "approve", "type": "approval", "name": "确认订单处理", "config": {"title": "确认订单自动处理", "description": "请核对订单信息，批准后调用通知接口。", "risk_level": "medium"}, "position": {"x": 520, "y": 160}},
                {"id": "notify", "type": "http", "name": "发送处理通知", "config": {"method": "POST", "url": "https://httpbin.org/post", "risk_level": "low", "body": {"order": "{{ nodes.extract.text }}"}}, "position": {"x": 780, "y": 160}},
                _end({"receipt": "{{ nodes.notify.body }}", "order_info": "{{ nodes.extract.text }}"}, x=1040),
            ],
            [
                {"id": "e1", "source": "start", "target": "extract", "source_port": "default", "target_port": "default"},
                {"id": "e2", "source": "extract", "target": "approve", "source_port": "default", "target_port": "default"},
                {"id": "e3", "source": "approve", "target": "notify", "source_port": "default", "target_port": "default"},
                {"id": "e4", "source": "notify", "target": "end", "source_port": "default", "target_port": "default"},
            ],
        ),
    ),
]

_BY_ID = {item.id: item for item in WORKFLOW_TEMPLATES}


def get_template(template_id: str) -> WorkflowTemplate | None:
    return _BY_ID.get(template_id)
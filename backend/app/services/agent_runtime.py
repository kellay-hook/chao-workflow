from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentProfile
from app.services import model_gateway
from app.services.expressions import evaluate
from app.services.tools import ApprovalRequired, ToolError, ToolExecutor

MAX_TEAM_TOKENS = 100_000


class AgentError(Exception):
    pass


@dataclass
class AgentResult:
    output: Any
    content: str
    tokens: int
    state: dict[str, Any] = field(default_factory=dict)


def _extract_json(content: str) -> Any:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:]
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(stripped[start : end + 1])
            except json.JSONDecodeError:
                pass
        return None


async def load_profile(session: AsyncSession, tenant_id: str, profile_id: str) -> AgentProfile:
    profile = await session.get(AgentProfile, profile_id)
    if not profile or profile.tenant_id != tenant_id:
        raise AgentError(f"agent profile {profile_id} not found")
    return profile


async def run_agent(
    session: AsyncSession,
    *,
    tenant_id: str,
    profile: AgentProfile,
    goal: str,
    context: dict[str, Any],
    state: dict[str, Any] | None = None,
    approved_tools: set[str] | None = None,
    agent_name: str | None = None,
) -> AgentResult:
    model_profile = await model_gateway.resolve_chat_profile(
        session, tenant_id, profile.model_profile_id
    )
    tool_executor = ToolExecutor(
        session,
        tenant_id,
        tool_ids=list(profile.tool_ids or []),
        kb_ids=list(profile.kb_ids or []),
        approved_tools=approved_tools or set(),
    )
    tool_schemas = await tool_executor.schemas()
    system_prompt = profile.role_prompt
    if profile.output_schema:
        system_prompt += "\nReturn only valid JSON that matches the requested output schema."
    state = state or {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": goal},
        ],
        "tokens": 0,
        "iterations": 0,
        "repairs": 0,
        "pending": None,
    }
    if not state.get("messages"):
        state["messages"] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": goal},
        ]

    pending = state.get("pending")
    if pending:
        call = pending.get("call") or {}
        try:
            result = await tool_executor.call(
                call.get("name", ""), call.get("arguments") or {}, approved=True
            )
        except ApprovalRequired:
            raise
        except ToolError as exc:
            result = {"error": str(exc)}
        state["messages"].append(
            {
                "role": "tool",
                "tool_call_id": call.get("id") or "pending",
                "name": call.get("name"),
                "content": json.dumps(result, ensure_ascii=False)[:20000],
            }
        )
        state["messages"].append(
            {
                "role": "user",
                "content": "The approved tool call completed. Continue toward the goal.",
            }
        )
        state["pending"] = None

    for _ in range(max(1, profile.max_iterations)):
        state["iterations"] = int(state.get("iterations", 0)) + 1
        response_format = None
        if profile.output_schema:
            response_format = {"type": "json_object"}
        try:
            result = await model_gateway.chat(
                model_profile,
                state["messages"],
                tools=tool_schemas or None,
                response_format=response_format,
            )
        except model_gateway.ModelError as exc:
            raise AgentError(str(exc)) from exc
        state["tokens"] = int(state.get("tokens", 0)) + result.tokens
        if state["tokens"] > MAX_TEAM_TOKENS:
            raise AgentError("agent token budget exceeded")

        if result.tool_calls:
            assistant_tool_calls = []
            for call in result.tool_calls:
                assistant_tool_calls.append(
                    {
                        "id": call.get("id") or f"call_{state['iterations']}",
                        "type": "function",
                        "function": {
                            "name": call.get("name") or "",
                            "arguments": json.dumps(call.get("arguments") or {}, ensure_ascii=False),
                        },
                    }
                )
            state["messages"].append(
                {"role": "assistant", "content": result.content or "", "tool_calls": assistant_tool_calls}
            )
            for call in result.tool_calls:
                name = call.get("name") or ""
                args = call.get("arguments") or {}
                if await tool_executor.requires_approval(name):
                    state["pending"] = {"call": call}
                    raise ApprovalRequired(
                        title=f"Approve tool call: {name}",
                        description=f"Agent {agent_name or profile.name} wants to call {name}.",
                        tool_name=name,
                        args=args,
                        risk_level=next(
                            (tool.risk_level for tool in tool_executor.tools.values() if tool.name == name),
                            "medium",
                        ),
                        agent_name=agent_name or profile.name,
                        state=state,
                    )
                try:
                    tool_result = await tool_executor.call(name, args, approved=True)
                except ToolError as exc:
                    tool_result = {"error": str(exc)}
                state["messages"].append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id") or f"call_{state['iterations']}",
                        "name": name,
                        "content": json.dumps(tool_result, ensure_ascii=False)[:20000],
                    }
                )
            continue

        content = result.content or ""
        if profile.output_schema:
            parsed = _extract_json(content)
            if parsed is None and state.get("repairs", 0) < 1:
                state["repairs"] = int(state.get("repairs", 0)) + 1
                state["messages"].append(
                    {
                        "role": "user",
                        "content": "Your previous answer was not valid JSON. Return only valid JSON matching the requested schema.",
                    }
                )
                continue
            if parsed is None:
                raise AgentError("agent did not return valid JSON")
            state["messages"].append({"role": "assistant", "content": content})
            return AgentResult(output=parsed, content=content, tokens=int(state.get("tokens", 0)), state=state)
        state["messages"].append({"role": "assistant", "content": content})
        return AgentResult(output=content, content=content, tokens=int(state.get("tokens", 0)), state=state)

    raise AgentError("agent exceeded maximum iterations")


async def _load_many(
    session: AsyncSession, tenant_id: str, profile_ids: list[str]
) -> dict[str, AgentProfile]:
    profiles: dict[str, AgentProfile] = {}
    for profile_id in profile_ids:
        profiles[profile_id] = await load_profile(session, tenant_id, profile_id)
    return profiles


async def run_agent_team(
    session: AsyncSession,
    *,
    tenant_id: str,
    config: dict[str, Any],
    goal: str,
    context: dict[str, Any],
    state: dict[str, Any] | None = None,
    approved_tools: set[str] | None = None,
) -> AgentResult:
    mode = config.get("mode")
    if mode == "supervisor":
        return await _run_supervisor(
            session,
            tenant_id=tenant_id,
            config=config,
            goal=goal,
            context=context,
            state=state,
            approved_tools=approved_tools,
        )
    if mode == "graph":
        return await _run_graph_team(
            session,
            tenant_id=tenant_id,
            config=config,
            goal=goal,
            context=context,
            state=state,
            approved_tools=approved_tools,
        )
    raise AgentError("agent_team mode must be supervisor or graph")


async def _run_supervisor(
    session: AsyncSession,
    *,
    tenant_id: str,
    config: dict[str, Any],
    goal: str,
    context: dict[str, Any],
    state: dict[str, Any] | None,
    approved_tools: set[str] | None,
) -> AgentResult:
    supervisor_id = config.get("supervisor_profile_id")
    worker_ids = list(config.get("worker_profile_ids") or [])
    if not supervisor_id:
        raise AgentError("supervisor_profile_id is required")
    supervisor = await load_profile(session, tenant_id, supervisor_id)
    workers = await _load_many(session, tenant_id, worker_ids)
    workers_by_name = {profile.name: profile for profile in workers.values()}
    model_profile = await model_gateway.resolve_chat_profile(
        session, tenant_id, supervisor.model_profile_id
    )
    max_handoffs = int(config.get("max_handoffs", 12))
    token_budget = int(config.get("token_budget", MAX_TEAM_TOKENS))
    state = state or {
        "mode": "supervisor",
        "messages": [
            {
                "role": "system",
                "content": (
                    supervisor.role_prompt
                    + "\nYou are a supervisor. Reply with JSON only. Use "
                    '{"action":"delegate","agent":"<name>","task":"..."} to delegate, '
                    'or {"action":"finish","result":...} when done. '
                    "Available workers: " + ", ".join(workers_by_name.keys())
                ),
            },
            {"role": "user", "content": goal},
        ],
        "handoffs": 0,
        "tokens": 0,
        "results": [],
        "worker_state": None,
        "worker_name": None,
        "worker_task": None,
    }

    if state.get("worker_state") and state.get("worker_name"):
        worker = workers_by_name.get(state["worker_name"])
        if not worker:
            raise AgentError("pending worker no longer exists")
        result = await run_agent(
            session,
            tenant_id=tenant_id,
            profile=worker,
            goal=state.get("worker_task") or goal,
            context=context,
            state=state["worker_state"],
            approved_tools=approved_tools,
            agent_name=worker.name,
        )
        state["results"].append({"agent": worker.name, "output": result.output})
        state["tokens"] += result.tokens
        state["messages"].append(
            {"role": "user", "content": f"Worker {worker.name} returned: {json.dumps(result.output, ensure_ascii=False)[:12000]}"}
        )
        state["worker_state"] = None
        state["worker_name"] = None
        state["worker_task"] = None

    while int(state.get("handoffs", 0)) < max_handoffs:
        result = await model_gateway.chat(
            model_profile,
            state["messages"],
            response_format={"type": "json_object"},
        )
        state["tokens"] += result.tokens
        if state["tokens"] > token_budget:
            raise AgentError("agent team token budget exceeded")
        parsed = _extract_json(result.content or "")
        if not isinstance(parsed, dict):
            state["messages"].append(
                {"role": "user", "content": "Return valid JSON with action delegate or finish."}
            )
            continue
        action = parsed.get("action")
        if action == "finish":
            output = parsed.get("result")
            return AgentResult(
                output=output,
                content=json.dumps(output, ensure_ascii=False),
                tokens=state["tokens"],
                state=state,
            )
        if action == "delegate":
            worker_name = str(parsed.get("agent") or "")
            task = str(parsed.get("task") or "")
            worker = workers_by_name.get(worker_name)
            if not worker:
                state["messages"].append(
                    {"role": "user", "content": f"Unknown worker {worker_name}. Choose one of {list(workers_by_name)}."}
                )
                continue
            state["handoffs"] = int(state.get("handoffs", 0)) + 1
            state["messages"].append(
                {"role": "assistant", "content": json.dumps(parsed, ensure_ascii=False)}
            )
            try:
                worker_result = await run_agent(
                    session,
                    tenant_id=tenant_id,
                    profile=worker,
                    goal=task,
                    context=context,
                    approved_tools=approved_tools,
                    agent_name=worker.name,
                )
            except ApprovalRequired as exc:
                state["worker_state"] = exc.state
                state["worker_name"] = worker.name
                state["worker_task"] = task
                exc.state = state
                raise
            state["results"].append({"agent": worker.name, "output": worker_result.output})
            state["tokens"] += worker_result.tokens
            state["messages"].append(
                {
                    "role": "user",
                    "content": f"Worker {worker.name} returned: {json.dumps(worker_result.output, ensure_ascii=False)[:12000]}",
                }
            )
            continue
        state["messages"].append(
            {"role": "user", "content": "Unknown action. Use delegate or finish."}
        )
    raise AgentError("agent team exceeded max_handoffs")


async def _run_graph_team(
    session: AsyncSession,
    *,
    tenant_id: str,
    config: dict[str, Any],
    goal: str,
    context: dict[str, Any],
    state: dict[str, Any] | None,
    approved_tools: set[str] | None,
) -> AgentResult:
    agents_config = list(config.get("agents") or [])
    if not agents_config:
        raise AgentError("graph mode requires agents")
    agents: dict[str, dict[str, Any]] = {}
    for item in agents_config:
        agent_id = str(item.get("id") or item.get("name") or "")
        if not agent_id:
            continue
        agents[agent_id] = item
    entry = str(config.get("entry_agent_id") or next(iter(agents), ""))
    if entry not in agents:
        raise AgentError("entry_agent_id is invalid")
    handoffs = list(config.get("handoffs") or [])
    max_steps = int(config.get("max_steps", 20))
    token_budget = int(config.get("token_budget", MAX_TEAM_TOKENS))
    state = state or {
        "mode": "graph",
        "current": entry,
        "steps": 0,
        "results": [],
        "tokens": 0,
        "agent_state": None,
        "pending_agent_id": None,
        "pending_goal": None,
    }

    if state.get("agent_state") and state.get("pending_agent_id"):
        agent_id = state["pending_agent_id"]
        agent_config = agents.get(agent_id) or {}
        profile = await load_profile(session, tenant_id, str(agent_config.get("profile_id") or ""))
        result = await run_agent(
            session,
            tenant_id=tenant_id,
            profile=profile,
            goal=state.get("pending_goal") or goal,
            context=context,
            state=state["agent_state"],
            approved_tools=approved_tools,
            agent_name=profile.name,
        )
        state["results"].append({"agent": agent_id, "output": result.output})
        state["tokens"] += result.tokens
        state["agent_state"] = None
        state["pending_agent_id"] = None
        state["pending_goal"] = None
        state["current"] = _next_agent(agent_id, result.output, handoffs, context)
        if not state["current"]:
            return AgentResult(
                output=result.output,
                content=result.content,
                tokens=state["tokens"],
                state=state,
            )

    while int(state.get("steps", 0)) < max_steps:
        current = str(state.get("current") or "")
        agent_config = agents.get(current)
        if not agent_config:
            raise AgentError(f"unknown agent node {current}")
        profile = await load_profile(session, tenant_id, str(agent_config.get("profile_id") or ""))
        task = goal
        if state["results"]:
            task = (
                goal
                + "\n\nPrevious results:\n"
                + json.dumps(state["results"][-3:], ensure_ascii=False)[:16000]
            )
        state["steps"] = int(state.get("steps", 0)) + 1
        try:
            result = await run_agent(
                session,
                tenant_id=tenant_id,
                profile=profile,
                goal=task,
                context=context,
                approved_tools=approved_tools,
                agent_name=profile.name,
            )
        except ApprovalRequired as exc:
            state["agent_state"] = exc.state
            state["pending_agent_id"] = current
            state["pending_goal"] = task
            exc.state = state
            raise
        state["results"].append({"agent": current, "output": result.output})
        state["tokens"] += result.tokens
        if state["tokens"] > token_budget:
            raise AgentError("agent team token budget exceeded")
        next_agent = _next_agent(current, result.output, handoffs, context)
        if not next_agent:
            return AgentResult(
                output=result.output,
                content=result.content,
                tokens=state["tokens"],
                state=state,
            )
        state["current"] = next_agent
    raise AgentError("agent graph exceeded max_steps")


def _next_agent(
    current: str, output: Any, handoffs: list[dict[str, Any]], context: dict[str, Any]
) -> str | None:
    scoped_context = dict(context)
    scoped_context["agent_output"] = output
    for handoff in handoffs:
        if str(handoff.get("from") or handoff.get("source") or "") != current:
            continue
        condition = handoff.get("when") or handoff.get("condition")
        if not condition or evaluate(str(condition), scoped_context):
            target = str(handoff.get("to") or handoff.get("target") or "")
            return target or None
    return None

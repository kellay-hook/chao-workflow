from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.events import emit
from app.models import (
    Approval,
    NodeRun,
    Tool,
    Workflow,
    WorkflowRun,
    WorkflowVersion,
    utcnow,
)
from app.schemas import EdgeModel, NodeModel, WorkflowDSL
from app.services import agent_runtime, expressions, model_gateway, rag, runner_client
from app.services.http_client import UnsafeUrlError, request_json
from app.services.inputs import prepare_run_inputs
from app.services.tools import ApprovalRequired, ToolExecutor


class EngineError(Exception):
    pass


class NodePaused(Exception):
    def __init__(
        self,
        *,
        node_id: str,
        title: str,
        description: str,
        args: dict[str, Any],
        risk_level: str = "medium",
        agent_name: str | None = None,
        tool_name: str | None = None,
    ) -> None:
        super().__init__(description or title)
        self.node_id = node_id
        self.title = title
        self.description = description
        self.arguments = args
        self.risk_level = risk_level
        self.agent_name = agent_name
        self.tool_name = tool_name


class RunCanceled(Exception):
    pass


@dataclass
class NodeResult:
    output: Any
    tokens: int = 0


class WorkflowEngine:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def execute_run(self, run_id: str, resume: dict[str, Any] | None = None) -> None:
        run = await self.session.get(WorkflowRun, run_id)
        if not run:
            raise EngineError("run not found")
        version = await self.session.get(WorkflowVersion, run.version_id)
        if not version:
            raise EngineError("workflow version not found")
        dsl = WorkflowDSL.model_validate(version.dsl)
        prepared_inputs, missing = prepare_run_inputs(version.dsl, run.inputs)
        if missing:
            raise EngineError(f"missing required inputs: {', '.join(missing)}")
        run.inputs = prepared_inputs
        state = dict(run.state or {})
        state.setdefault("node_outputs", {})
        state.setdefault("edge_states", {})
        state.setdefault("executed", [])
        state.setdefault("skipped", [])
        state.setdefault("depth", 0)
        if resume:
            state["resume"] = resume
        run.status = "running"
        run.started_at = run.started_at or utcnow()
        await emit(
            self.session,
            run_id=run.id,
            tenant_id=run.tenant_id,
            event_type="run.started",
            data={"workflow_id": run.workflow_id, "version_id": run.version_id},
        )
        await self.session.flush()
        try:
            output = await self._execute_dag(run, dsl, state)
            run.status = "succeeded"
            run.output = output
            run.error = None
            run.finished_at = utcnow()
            state["paused"] = None
            run.state = dict(state)
            await emit(
                self.session,
                run_id=run.id,
                tenant_id=run.tenant_id,
                event_type="run.succeeded",
                data={"output": output},
            )
        except NodePaused as paused:
            approval = Approval(
                tenant_id=run.tenant_id,
                run_id=run.id,
                node_id=paused.node_id,
                agent_name=paused.agent_name,
                tool_name=paused.tool_name,
                title=paused.title,
                description=paused.description,
                args=paused.arguments,
                risk_level=paused.risk_level,
                status="pending",
                assignee_role="editor",
                expires_at=utcnow() + timedelta(hours=24),
            )
            self.session.add(approval)
            await self.session.flush()
            run.status = "waiting_approval"
            state["paused"] = {
                "node_id": paused.node_id,
                "approval_id": approval.id,
                "risk_level": paused.risk_level,
            }
            run.state = dict(state)
            await emit(
                self.session,
                run_id=run.id,
                tenant_id=run.tenant_id,
                event_type="run.waiting_approval",
                node_id=paused.node_id,
                data={"approval_id": approval.id, "title": paused.title, "risk_level": paused.risk_level},
            )
        except (RunCanceled, asyncio.CancelledError):
            run.status = "canceled"
            run.finished_at = utcnow()
            run.state = dict(state)
            await emit(
                self.session,
                run_id=run.id,
                tenant_id=run.tenant_id,
                event_type="run.canceled",
                data={},
            )
        except Exception as exc:
            run.status = "failed"
            run.error = {"message": str(exc), "type": type(exc).__name__}
            run.finished_at = utcnow()
            run.state = dict(state)
            await emit(
                self.session,
                run_id=run.id,
                tenant_id=run.tenant_id,
                event_type="run.failed",
                data={"error": run.error},
            )
        await self.session.flush()

    async def _execute_dag(
        self, run: WorkflowRun, dsl: WorkflowDSL, state: dict[str, Any]
    ) -> Any:
        nodes = {node.id: node for node in dsl.nodes}
        edges = list(dsl.edges)
        incoming: dict[str, list[EdgeModel]] = {node_id: [] for node_id in nodes}
        outgoing: dict[str, list[EdgeModel]] = {node_id: [] for node_id in nodes}
        for edge in edges:
            if edge.source in outgoing and edge.target in incoming:
                outgoing[edge.source].append(edge)
                incoming[edge.target].append(edge)
        start_nodes = [node for node in dsl.nodes if node.type == "start"]
        if not start_nodes:
            raise EngineError("workflow has no start node")
        start_id = start_nodes[0].id
        edge_states: dict[str, str] = state.get("edge_states", {})
        executed: list[str] = state.get("executed", [])
        skipped: list[str] = state.get("skipped", [])
        node_outputs: dict[str, Any] = state.get("node_outputs", {})
        paused = state.get("paused")
        forced: list[str] = []
        if paused and paused.get("node_id"):
            forced.append(paused["node_id"])
            if paused["node_id"] in executed:
                executed.remove(paused["node_id"])
        ready: list[str] = forced or [start_id]
        max_steps = max(1, len(nodes) * 3 + 20)
        steps = 0
        final_output: Any = None

        while ready and steps < max_steps:
            steps += 1
            if run.cancel_requested:
                raise RunCanceled()
            node_id = ready.pop(0)
            if node_id in executed or node_id in skipped:
                continue
            node = nodes.get(node_id)
            if not node:
                continue
            is_forced = bool(forced and node_id == forced[0])
            if not is_forced and node.type != "start":
                unresolved = [edge for edge in incoming[node_id] if edge.id not in edge_states]
                if unresolved:
                    ready.append(node_id)
                    if len(ready) > len(nodes) * 2:
                        raise EngineError(f"deadlock near node {node_id}")
                    continue
                active = [edge for edge in incoming[node_id] if edge_states.get(edge.id) == "active"]
                if not active:
                    self._skip_node(node_id, outgoing, edge_states, skipped, ready)
                    continue
            context = expressions.build_context(
                inputs=run.inputs,
                node_outputs=node_outputs,
                run={
                    "id": run.id,
                    "workflow_id": run.workflow_id,
                    "version_id": run.version_id,
                    "parent_run_id": run.parent_run_id,
                },
            )
            reused_run = None
            if is_forced:
                existing = await self.session.execute(
                    select(NodeRun)
                    .where(
                        NodeRun.run_id == run.id,
                        NodeRun.node_id == node.id,
                        NodeRun.status == "waiting_approval",
                    )
                    .order_by(NodeRun.created_at.desc())
                )
                reused_run = existing.scalars().first()
            if reused_run:
                node_run = reused_run
                node_run.status = "running"
                node_run.attempt += 1
                node_run.started_at = utcnow()
            else:
                node_run = NodeRun(
                    run_id=run.id,
                    tenant_id=run.tenant_id,
                    node_id=node.id,
                    node_type=node.type,
                    status="running",
                    attempt=1,
                    input={"config": node.config, "context_inputs": run.inputs},
                    started_at=utcnow(),
                )
                self.session.add(node_run)
            await self.session.flush()
            await emit(
                self.session,
                run_id=run.id,
                tenant_id=run.tenant_id,
                event_type="node.started",
                node_id=node.id,
                data={"node_type": node.type, "name": node.name},
            )
            try:
                result = await self._run_node_with_timeout(
                    run, node, context, state, node_run
                )
            except NodePaused:
                node_run.status = "waiting_approval"
                await self.session.flush()
                state["edge_states"] = edge_states
                state["executed"] = executed
                state["skipped"] = skipped
                state["node_outputs"] = node_outputs
                raise
            except Exception as exc:
                node_run.status = "failed"
                node_run.error = {"message": str(exc), "type": type(exc).__name__}
                node_run.finished_at = utcnow()
                await emit(
                    self.session,
                    run_id=run.id,
                    tenant_id=run.tenant_id,
                    event_type="node.failed",
                    node_id=node.id,
                    data={"error": node_run.error},
                )
                if not bool(node.config.get("continue_on_error")):
                    raise
                result = NodeResult(output={"error": str(exc)})
            node_run.status = "succeeded"
            node_run.output = {"value": result.output}
            node_run.tokens = result.tokens
            node_run.finished_at = utcnow()
            run.token_usage += result.tokens
            executed.append(node.id)
            node_outputs[node.id] = result.output
            await emit(
                self.session,
                run_id=run.id,
                tenant_id=run.tenant_id,
                event_type="node.succeeded",
                node_id=node.id,
                data={"output": result.output, "tokens": result.tokens},
            )
            active_edges: list[EdgeModel] = []
            if node.type == "condition":
                case_id = str((result.output or {}).get("case") or "default")
                for edge in outgoing[node.id]:
                    if edge.source_port == case_id or (case_id == "default" and edge.source_port == "default"):
                        active_edges.append(edge)
            else:
                active_edges = list(outgoing[node.id])
            active_ids = {edge.id for edge in active_edges}
            for edge in outgoing[node.id]:
                edge_states[edge.id] = "active" if edge.id in active_ids else "skipped"
            for edge in outgoing[node.id]:
                target = edge.target
                if target in executed or target in skipped:
                    continue
                if all(item.id in edge_states for item in incoming[target]):
                    if any(edge_states.get(item.id) == "active" for item in incoming[target]):
                        if target not in ready:
                            ready.append(target)
                    else:
                        self._skip_node(target, outgoing, edge_states, skipped, ready)
                elif target not in ready:
                    ready.append(target)
            if node.type == "end":
                final_output = result.output
            state["edge_states"] = edge_states
            state["executed"] = executed
            state["skipped"] = skipped
            state["node_outputs"] = node_outputs
            state["paused"] = None
            run.state = dict(state)
            await self.session.flush()

        if not final_output and executed:
            end_nodes = [node_id for node_id in executed if nodes.get(node_id) and nodes[node_id].type == "end"]
            if end_nodes:
                final_output = node_outputs.get(end_nodes[-1])
        if final_output is None:
            final_output = {"output": None}
        return final_output

    def _skip_node(
        self,
        node_id: str,
        outgoing: dict[str, list[EdgeModel]],
        edge_states: dict[str, str],
        skipped: list[str],
        ready: list[str],
    ) -> None:
        if node_id in skipped:
            return
        skipped.append(node_id)
        for edge in outgoing.get(node_id, []):
            edge_states[edge.id] = "skipped"
            if edge.target not in ready:
                ready.append(edge.target)

    async def _run_node_with_timeout(
        self,
        run: WorkflowRun,
        node: NodeModel,
        context: dict[str, Any],
        state: dict[str, Any],
        node_run: NodeRun,
    ) -> NodeResult:
        timeout = int(node.config.get("timeout_sec") or 120)
        if node.type in {"agent", "agent_team"}:
            timeout = int(node.config.get("timeout_sec") or 600)
        if node.type == "approval":
            timeout = int(node.config.get("timeout_sec") or 86400)
        try:
            return await asyncio.wait_for(
                self._run_node(run, node, context, state, node_run), timeout=timeout
            )
        except TimeoutError as exc:
            raise EngineError(f"node {node.id} timed out after {timeout}s") from exc

    async def _run_node(
        self,
        run: WorkflowRun,
        node: NodeModel,
        context: dict[str, Any],
        state: dict[str, Any],
        node_run: NodeRun,
    ) -> NodeResult:
        config = node.config
        resume = state.get("resume") if state.get("paused") and state["paused"].get("node_id") == node.id else None
        if resume and not resume.get("approved", False) and node.type in {"tool", "http", "agent", "agent_team"}:
            raise EngineError("approval rejected")
        if node.type == "start":
            return NodeResult(output={"inputs": run.inputs})
        if node.type == "end":
            outputs = config.get("outputs")
            if isinstance(outputs, dict):
                return NodeResult(output={key: expressions.render(value, context) for key, value in outputs.items()})
            if "output" in config:
                return NodeResult(output={"output": expressions.render_json(config.get("output"), context)})
            return NodeResult(output={"output": context.get("nodes", {})})
        if node.type == "llm":
            return await self._run_llm(run, node, context)
        if node.type == "condition":
            cases = config.get("cases") or []
            case_id = expressions.first_case(cases, context)
            return NodeResult(output={"case": case_id})
        if node.type == "approval":
            if resume:
                if not resume.get("approved"):
                    raise EngineError("approval rejected")
                return NodeResult(output={"approved": True, "comment": resume.get("comment", "")})
            raise NodePaused(
                node_id=node.id,
                title=str(expressions.render(config.get("title") or "Approval required", context)),
                description=str(expressions.render(config.get("description") or "", context)),
                args={"node": node.id, "inputs": run.inputs},
                risk_level=str(config.get("risk_level") or "medium"),
            )
        if node.type == "http":
            return await self._run_http(run, node, context, state, resume)
        if node.type == "tool":
            return await self._run_tool(run, node, context, state, resume)
        if node.type == "code":
            return await self._run_code(node, context)
        if node.type == "agent":
            return await self._run_agent(run, node, context, state, resume)
        if node.type == "agent_team":
            return await self._run_agent_team(run, node, context, state, resume)
        if node.type == "subworkflow":
            return await self._run_subworkflow(run, node, context, state)
        if node.type == "loop":
            return await self._run_loop(run, node, context, state)
        raise EngineError(f"unsupported node type {node.type}")

    async def _run_llm(self, run: WorkflowRun, node: NodeModel, context: dict[str, Any]) -> NodeResult:
        config = node.config
        profile = await model_gateway.resolve_chat_profile(
            self.session, run.tenant_id, config.get("model_profile_id")
        )
        messages = config.get("messages")
        if not messages:
            prompt = config.get("prompt") or context.get("inputs", {}).get("prompt") or ""
            messages = [{"role": "user", "content": str(prompt)}]
        rendered_messages = []
        for message in messages:
            rendered_messages.append(
                {
                    "role": message.get("role", "user"),
                    "content": str(expressions.render(message.get("content", ""), context)),
                }
            )
        response_format = None
        if config.get("response_format") == "json" or config.get("output_schema"):
            response_format = {"type": "json_object"}
            if not any("json" in str(message.get("content", "")).lower() for message in rendered_messages):
                rendered_messages.insert(0, {"role": "system", "content": "Return only valid JSON."})
        result = await model_gateway.chat(profile, rendered_messages, response_format=response_format)
        output: dict[str, Any] = {"text": result.content}
        if response_format:
            try:
                output["json"] = json.loads(result.content)
            except json.JSONDecodeError:
                output["json"] = None
        return NodeResult(output=output, tokens=result.tokens)

    async def _run_http(
        self,
        run: WorkflowRun,
        node: NodeModel,
        context: dict[str, Any],
        state: dict[str, Any],
        resume: dict[str, Any] | None,
    ) -> NodeResult:
        config = node.config
        method = str(config.get("method") or "GET").upper()
        risk = str(config.get("risk_level") or ("medium" if method != "GET" else "low"))
        if risk in {"medium", "high"} and method != "GET" and not (resume and resume.get("approved")):
            raise NodePaused(
                node_id=node.id,
                title=str(expressions.render(config.get("approval_title") or f"Approve HTTP {method}", context)),
                description=str(expressions.render(config.get("approval_description") or "A workflow wants to perform a write request.", context)),
                args={"method": method, "url": expressions.render(config.get("url"), context)},
                risk_level=risk,
            )
        url = str(expressions.render(config.get("url") or "", context))
        headers = expressions.render(config.get("headers") or {}, context)
        params = expressions.render(config.get("params") or {}, context)
        body = expressions.render_json(config.get("body"), context) if "body" in config else None
        try:
            result = await request_json(
                method=method,
                url=url,
                headers=headers,
                params=params,
                body=body,
                timeout_sec=int(config.get("timeout_sec") or 30),
                allowed_domains=list(config.get("allowed_domains") or []),
            )
        except UnsafeUrlError as exc:
            raise EngineError(str(exc)) from exc
        return NodeResult(
            output={"status_code": result.status_code, "body": result.body, "text": result.text[:4000]}
        )

    async def _run_tool(
        self,
        run: WorkflowRun,
        node: NodeModel,
        context: dict[str, Any],
        state: dict[str, Any],
        resume: dict[str, Any] | None,
    ) -> NodeResult:
        config = node.config
        tool_id = str(config.get("tool_id") or "")
        if tool_id == "knowledge_search" or tool_id.startswith("builtin:"):
            kb_ids = list(config.get("kb_ids") or [])
            query = str(expressions.render(config.get("input", {}).get("query") or context.get("inputs", {}).get("query") or "", context))
            result = await rag.search(
                self.session,
                tenant_id=run.tenant_id,
                kb_ids=kb_ids,
                query=query,
                top_k=int(config.get("input", {}).get("top_k") or 8),
            )
            return NodeResult(output=result.model_dump())
        tool = await self.session.get(Tool, tool_id)
        if not tool or tool.tenant_id != run.tenant_id:
            raise EngineError("tool not found")
        executor = ToolExecutor(
            self.session,
            run.tenant_id,
            tool_ids=[tool.id],
            approved_tools={tool.name} if resume and resume.get("approved") else set(),
        )
        inputs = expressions.render(config.get("input") or {}, context)
        try:
            output = await executor.call(tool.name, inputs, approved=bool(resume and resume.get("approved")))
        except ApprovalRequired as exc:
            raise NodePaused(
                node_id=node.id,
                title=exc.title,
                description=exc.description,
                args=exc.arguments,
                risk_level=exc.risk_level,
            ) from exc
        return NodeResult(output=output)

    async def _run_code(self, node: NodeModel, context: dict[str, Any]) -> NodeResult:
        config = node.config
        source = str(config.get("source") or "")
        if not source.strip():
            raise EngineError("code node has no source")
        inputs = expressions.render(config.get("input") or context.get("inputs") or {}, context)
        result = await runner_client.execute_code(
            source,
            inputs if isinstance(inputs, dict) else {"input": inputs},
            timeout_sec=int(config.get("timeout_sec") or settings.runner_timeout_seconds),
            memory_mb=int(config.get("memory_mb") or settings.runner_memory_mb),
        )
        if result.get("error"):
            raise EngineError(str(result["error"]))
        return NodeResult(output=result.get("output", result))

    async def _run_agent(
        self,
        run: WorkflowRun,
        node: NodeModel,
        context: dict[str, Any],
        state: dict[str, Any],
        resume: dict[str, Any] | None,
    ) -> NodeResult:
        config = node.config
        profile = await agent_runtime.load_profile(
            self.session, run.tenant_id, str(config.get("agent_profile_id") or "")
        )
        goal = str(
            expressions.render(
                config.get("goal") or config.get("prompt") or context.get("inputs", {}).get("goal") or "",
                context,
            )
        )
        agent_state = state.get("agent_state") if resume else None
        previous_tokens = int(agent_state.get("tokens", 0)) if agent_state else 0
        approved_tools = {str(resume.get("tool_name"))} if resume and resume.get("tool_name") else set()
        try:
            result = await agent_runtime.run_agent(
                self.session,
                tenant_id=run.tenant_id,
                profile=profile,
                goal=goal,
                context=context,
                state=agent_state,
                approved_tools=approved_tools,
                agent_name=profile.name,
            )
        except ApprovalRequired as exc:
            state["agent_state"] = exc.state
            raise NodePaused(
                node_id=node.id,
                title=exc.title,
                description=exc.description,
                args=exc.arguments,
                risk_level=exc.risk_level,
                agent_name=exc.agent_name,
                tool_name=exc.tool_name,
            ) from exc
        state["agent_state"] = None
        return NodeResult(output=result.output, tokens=max(0, result.tokens - previous_tokens))

    async def _run_agent_team(
        self,
        run: WorkflowRun,
        node: NodeModel,
        context: dict[str, Any],
        state: dict[str, Any],
        resume: dict[str, Any] | None,
    ) -> NodeResult:
        config = node.config
        goal = str(
            expressions.render(
                config.get("goal") or config.get("prompt") or context.get("inputs", {}).get("goal") or "",
                context,
            )
        )
        team_state = state.get("team_state") if resume else None
        previous_tokens = int(team_state.get("tokens", 0)) if team_state else 0
        approved_tools = {str(resume.get("tool_name"))} if resume and resume.get("tool_name") else set()
        try:
            result = await agent_runtime.run_agent_team(
                self.session,
                tenant_id=run.tenant_id,
                config=config,
                goal=goal,
                context=context,
                state=team_state,
                approved_tools=approved_tools,
            )
        except ApprovalRequired as exc:
            state["team_state"] = exc.state
            raise NodePaused(
                node_id=node.id,
                title=exc.title,
                description=exc.description,
                args=exc.arguments,
                risk_level=exc.risk_level,
                agent_name=exc.agent_name,
                tool_name=exc.tool_name,
            ) from exc
        state["team_state"] = None
        return NodeResult(output=result.output, tokens=max(0, result.tokens - previous_tokens))

    async def _run_subworkflow(
        self,
        run: WorkflowRun,
        node: NodeModel,
        context: dict[str, Any],
        state: dict[str, Any],
    ) -> NodeResult:
        depth = int(state.get("depth", 0)) + 1
        if depth > 3:
            raise EngineError("subworkflow depth limit exceeded")
        version_id = str(node.config.get("workflow_version_id") or "")
        version = await self.session.get(WorkflowVersion, version_id)
        if not version or version.tenant_id != run.tenant_id:
            raise EngineError("subworkflow version not found")
        workflow = await self.session.get(Workflow, version.workflow_id)
        if not workflow:
            raise EngineError("subworkflow not found")
        inputs = expressions.render(node.config.get("input") or {}, context)
        child = WorkflowRun(
            tenant_id=run.tenant_id,
            workflow_id=version.workflow_id,
            version_id=version.id,
            status="queued",
            trigger_type="subworkflow",
            inputs=inputs if isinstance(inputs, dict) else {"input": inputs},
            parent_run_id=run.id,
            created_by=run.created_by,
            state={"depth": depth},
        )
        self.session.add(child)
        await self.session.flush()
        await self.execute_run(child.id)
        if child.status != "succeeded":
            raise EngineError(f"subworkflow failed: {child.error}")
        return NodeResult(output=child.output or {})

    async def _run_loop(
        self,
        run: WorkflowRun,
        node: NodeModel,
        context: dict[str, Any],
        state: dict[str, Any],
    ) -> NodeResult:
        items = expressions.search(str(node.config.get("items_expr") or ""), context, default=[])
        if not isinstance(items, list):
            raise EngineError("loop items_expr must resolve to a list")
        max_iterations = min(int(node.config.get("max_iterations") or 100), 200)
        if len(items) > max_iterations:
            raise EngineError(f"loop has {len(items)} items, limit is {max_iterations}")
        results = []
        for index, item in enumerate(items):
            item_context = dict(context)
            item_context["item"] = item
            item_context["index"] = index
            inputs = expressions.render(node.config.get("input") or {"item": "{{ item }}", "index": "{{ index }}"}, item_context)
            version_id = str(node.config.get("workflow_version_id") or "")
            version = await self.session.get(WorkflowVersion, version_id)
            if not version or version.tenant_id != run.tenant_id:
                raise EngineError("loop subworkflow version not found")
            child = WorkflowRun(
                tenant_id=run.tenant_id,
                workflow_id=version.workflow_id,
                version_id=version.id,
                status="queued",
                trigger_type="loop",
                inputs=inputs if isinstance(inputs, dict) else {"input": inputs},
                parent_run_id=run.id,
                created_by=run.created_by,
                state={"depth": int(state.get("depth", 0)) + 1},
            )
            self.session.add(child)
            await self.session.flush()
            await self.execute_run(child.id)
            results.append(child.output if child.status == "succeeded" else {"error": child.error})
        return NodeResult(output={"items": results})





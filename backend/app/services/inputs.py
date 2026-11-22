from __future__ import annotations

import json
import re
from typing import Any

INPUT_REF = re.compile(r"inputs\.([A-Za-z_][A-Za-z0-9_]*)")


def _reachable_nodes(dsl: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = list(dsl.get("nodes", []))
    edges = list(dsl.get("edges", []))
    by_id = {str(node.get("id")): node for node in nodes if node.get("id")}
    start = next((str(node.get("id")) for node in nodes if node.get("type") == "start" and node.get("id")), None)
    if not start:
        return nodes
    adjacency: dict[str, list[str]] = {node_id: [] for node_id in by_id}
    for edge in edges:
        source, target = str(edge.get("source") or ""), str(edge.get("target") or "")
        if source in adjacency and target in by_id:
            adjacency[source].append(target)
    seen: set[str] = set()
    queue = [start]
    while queue:
        current = queue.pop()
        if current in seen:
            continue
        seen.add(current)
        queue.extend(adjacency.get(current, []))
    return [node for node_id, node in by_id.items() if node_id in seen]


def inferred_input_names(dsl: dict[str, Any]) -> list[str]:
    payload = json.dumps(_reachable_nodes(dsl), ensure_ascii=False, default=str)
    return sorted(set(INPUT_REF.findall(payload)))


def workflow_input_schema(dsl: dict[str, Any]) -> dict[str, Any]:
    schema = dsl.get("inputs") or {}
    properties = dict(schema.get("properties") or {})
    inferred = inferred_input_names(dsl)
    for name in inferred:
        properties.setdefault(name, {"type": "string", "title": name, "description": "Workflow input"})
    explicit_properties = bool(schema.get("properties"))
    explicit_required = schema.get("required")
    if explicit_required is not None and (explicit_properties or explicit_required):
        required = list(explicit_required)
    else:
        required = sorted(properties.keys())
    return {"type": "object", "properties": properties, "required": required}


def prepare_run_inputs(dsl: dict[str, Any], values: dict[str, Any] | None) -> tuple[dict[str, Any], list[str]]:
    schema = workflow_input_schema(dsl)
    prepared = dict(values or {})
    missing: list[str] = []
    for name in schema.get("required", []):
        if name not in prepared or prepared[name] in (None, ""):
            default = (schema.get("properties", {}).get(name) or {}).get("default")
            if default is not None:
                prepared[name] = default
            else:
                missing.append(name)
    return prepared, sorted(set(missing))

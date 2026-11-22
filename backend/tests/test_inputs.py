from __future__ import annotations

from app.services.inputs import prepare_run_inputs, workflow_input_schema


def test_schema_required_wins_and_unreachable_nodes_are_ignored():
    dsl = {
        "inputs": {
            "type": "object",
            "properties": {"topic": {"type": "string", "default": "agents"}},
            "required": ["topic"],
        },
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {"id": "team", "type": "agent_team", "config": {"goal": "{{ inputs.topic }}"}},
            {"id": "orphan", "type": "llm", "config": {"prompt": "{{ inputs.prompt }}"}},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "team"}],
    }
    schema = workflow_input_schema(dsl)
    assert schema["required"] == ["topic"]
    prepared, missing = prepare_run_inputs(dsl, {})
    assert missing == []
    assert prepared["topic"] == "agents"


def test_empty_schema_infers_reachable_inputs():
    dsl = {
        "inputs": {"type": "object", "properties": {}},
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {"id": "llm", "type": "llm", "config": {"prompt": "{{ inputs.question }}"}},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "llm"}],
    }
    schema = workflow_input_schema(dsl)
    assert "question" in schema["properties"]
    assert schema["required"] == ["question"]
    _, missing = prepare_run_inputs(dsl, {})
    assert missing == ["question"]

from __future__ import annotations

from app.schemas import validate_dsl


def valid_dsl():
    return {
        "schema_version": "1.0",
        "inputs": {"type": "object", "properties": {}},
        "nodes": [
            {"id": "start", "type": "start", "name": "Start", "config": {}},
            {"id": "end", "type": "end", "name": "End", "config": {}},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "end"}],
        "settings": {"timeout_sec": 60, "max_parallel": 2, "on_error": "fail"},
    }


def test_valid_workflow():
    result = validate_dsl(valid_dsl())
    assert result.valid, result.issues


def test_missing_start_is_invalid():
    dsl = valid_dsl()
    dsl["nodes"] = [node for node in dsl["nodes"] if node["type"] != "start"]
    result = validate_dsl(dsl)
    assert not result.valid
    assert any(issue.code == "start_count" for issue in result.issues)


def test_cycle_is_rejected():
    dsl = valid_dsl()
    dsl["nodes"].append({"id": "llm", "type": "llm", "config": {"model_profile_id": "m"}})
    dsl["edges"] = [
        {"id": "e1", "source": "start", "target": "llm"},
        {"id": "e2", "source": "llm", "target": "end"},
        {"id": "e3", "source": "end", "target": "llm"},
    ]
    result = validate_dsl(dsl)
    assert not result.valid
    assert any(issue.code in {"cycle", "end_outgoing"} for issue in result.issues)


def test_condition_ports_are_checked():
    dsl = valid_dsl()
    dsl["nodes"].append(
        {
            "id": "cond",
            "type": "condition",
            "config": {"cases": [{"id": "yes", "expr": "inputs.ok"}]},
        }
    )
    dsl["edges"] = [
        {"id": "e1", "source": "start", "target": "cond"},
        {"id": "e2", "source": "cond", "target": "end", "source_port": "nope"},
    ]
    result = validate_dsl(dsl)
    assert not result.valid
    assert any(issue.code == "condition_port" for issue in result.issues)

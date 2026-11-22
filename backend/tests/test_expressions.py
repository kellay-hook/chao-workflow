from __future__ import annotations

from app.services import expressions


def test_render_nested_templates():
    context = expressions.build_context(inputs={"name": "Ada"}, node_outputs={"n1": {"text": "hello"}})
    value = {"message": "{{ inputs.name }} / {{ nodes.n1.text }}"}
    assert expressions.render(value, context) == {"message": "Ada / hello"}


def test_jmespath_search():
    context = {"inputs": {"items": [1, 2, 3]}}
    assert expressions.search("inputs.items[1]", context) == 2


def test_first_case_default():
    context = {"inputs": {"score": 10}}
    cases = [
        {"id": "high", "expr": "inputs.score > 90"},
        {"id": "mid", "expr": "inputs.score > 50"},
    ]
    assert expressions.first_case(cases, context) == "default"


def test_render_json_parses_objects():
    context = {"inputs": {"x": 1}}
    assert expressions.render_json('{"value": {{ inputs.x }}}', context) == {"value": 1}

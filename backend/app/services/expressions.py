from __future__ import annotations

import ast
import json
import re
from typing import Any

import jmespath
from jinja2 import StrictUndefined, TemplateError
from jinja2.sandbox import SandboxedEnvironment

from app.schemas import ValidationIssue

_env = SandboxedEnvironment(undefined=StrictUndefined, autoescape=False)


class ExpressionError(Exception):
    pass


def build_context(
    *,
    inputs: dict[str, Any] | None = None,
    node_outputs: dict[str, Any] | None = None,
    run: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "inputs": inputs or {},
        "nodes": node_outputs or {},
        "run": run or {},
    }


def render(value: Any, context: dict[str, Any]) -> Any:
    if isinstance(value, str):
        pure = re.fullmatch(r"\s*\{\{\s*(.+?)\s*\}\}\s*", value, re.DOTALL)
        if pure:
            try:
                expression = _env.compile_expression(pure.group(1), undefined_to_none=False)
                return expression(**context)
            except Exception:
                pass
        if "{{" in value or "{%" in value:
            try:
                return _env.from_string(value).render(**context)
            except TemplateError as exc:
                raise ExpressionError(str(exc)) from exc
        return value
    if isinstance(value, dict):
        return {key: render(item, context) for key, item in value.items()}
    if isinstance(value, list):
        return [render(item, context) for item in value]
    return value


def render_json(value: Any, context: dict[str, Any]) -> Any:
    rendered = render(value, context)
    if isinstance(rendered, str):
        stripped = rendered.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                return rendered
    return rendered


def search(expression: str, context: dict[str, Any], default: Any = None) -> Any:
    if not expression:
        return context
    try:
        result = jmespath.search(expression, context)
    except Exception as exc:
        raise ExpressionError(f"invalid JMESPath expression: {exc}") from exc
    return default if result is None else result


def _eval_node(node: ast.AST, context: dict[str, Any]) -> Any:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, context)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in {"true", "True"}:
            return True
        if node.id in {"false", "False"}:
            return False
        if node.id in {"null", "None"}:
            return None
        if node.id not in context:
            raise ExpressionError(f"unknown variable: {node.id}")
        return context[node.id]
    if isinstance(node, ast.Attribute):
        value = _eval_node(node.value, context)
        if isinstance(value, dict):
            return value.get(node.attr)
        return getattr(value, node.attr, None)
    if isinstance(node, ast.Subscript):
        value = _eval_node(node.value, context)
        key = _eval_node(node.slice, context)
        try:
            return value[key]
        except Exception:
            return None
    if isinstance(node, ast.UnaryOp):
        value = _eval_node(node.operand, context)
        if isinstance(node.op, ast.Not):
            return not value
        if isinstance(node.op, ast.USub):
            return -value
        raise ExpressionError("unsupported unary operator")
    if isinstance(node, ast.BoolOp):
        values = [_eval_node(item, context) for item in node.values]
        if isinstance(node.op, ast.And):
            return all(values)
        if isinstance(node.op, ast.Or):
            return any(values)
        raise ExpressionError("unsupported boolean operator")
    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, context)
        for operator, comparator in zip(node.ops, node.comparators, strict=False):
            right = _eval_node(comparator, context)
            if isinstance(operator, ast.Eq):
                ok = left == right
            elif isinstance(operator, ast.NotEq):
                ok = left != right
            elif isinstance(operator, ast.Gt):
                ok = left > right
            elif isinstance(operator, ast.GtE):
                ok = left >= right
            elif isinstance(operator, ast.Lt):
                ok = left < right
            elif isinstance(operator, ast.LtE):
                ok = left <= right
            elif isinstance(operator, ast.In):
                ok = left in right
            elif isinstance(operator, ast.NotIn):
                ok = left not in right
            elif isinstance(operator, ast.Is):
                ok = left is right
            elif isinstance(operator, ast.IsNot):
                ok = left is not right
            else:
                raise ExpressionError("unsupported comparison operator")
            if not ok:
                return False
            left = right
        return True
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_eval_node(item, context) for item in node.elts]
    if isinstance(node, ast.Dict):
        return {
            _eval_node(key, context): _eval_node(value, context)
            for key, value in zip(node.keys, node.values, strict=False)
        }
    raise ExpressionError(f"unsupported expression node: {type(node).__name__}")


def evaluate(expression: str | None, context: dict[str, Any]) -> bool:
    if not expression:
        return True
    stripped = expression.strip()
    if stripped.lower() in {"true", "1"}:
        return True
    if stripped.lower() in {"false", "0"}:
        return False
    try:
        tree = ast.parse(stripped, mode="eval")
        return bool(_eval_node(tree, context))
    except ExpressionError:
        raise
    except SyntaxError:
        return bool(search(stripped, context))


def first_case(cases: list[dict[str, Any]], context: dict[str, Any]) -> str:
    for case in cases:
        if evaluate(case.get("expr"), context):
            return str(case.get("id", "default"))
    return "default"


def issues_from_error(exc: Exception) -> list[ValidationIssue]:
    return [ValidationIssue(code="expression_error", message=str(exc))]

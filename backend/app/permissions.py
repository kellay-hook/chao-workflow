from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException, Request, status

from app.deps import Principal, require_tenant

ALL_PERMISSIONS = {
    "workspace.read",
    "member.read",
    "member.invite",
    "member.update",
    "member.remove",
    "workflow.read",
    "workflow.create",
    "workflow.update",
    "workflow.delete",
    "workflow.publish",
    "workflow.run",
    "run.read",
    "run.cancel",
    "run.retry",
    "approval.read",
    "approval.decide",
    "knowledge.read",
    "knowledge.write",
    "knowledge.upload",
    "agent.read",
    "agent.run",
    "agent.write",
    "agent.test",
    "tool.read",
    "tool.write",
    "tool.test",
    "plugin.read",
    "plugin.install",
    "plugin.uninstall",
    "plugin.test",
    "model.read",
    "model.manage",
    "secret.manage",
    "audit.read",
    "usage.read",
    "apikey.manage",
    "settings.read",
    "settings.update",
}

READ_ONLY = {
    "workspace.read",
    "member.read",
    "workflow.read",
    "run.read",
    "approval.read",
    "knowledge.read",
    "agent.read",
    "tool.read",
    "plugin.read",
    "model.read",
    "settings.read",
    "usage.read",
}

RUNNER_PERMISSIONS = READ_ONLY | {
    "workflow.run",
    "agent.run",
    "run.cancel",
    "run.retry",
}

EDITOR_PERMISSIONS = RUNNER_PERMISSIONS | {
    "approval.decide",
    "workflow.create",
    "workflow.update",
    "workflow.delete",
    "workflow.publish",
    "knowledge.write",
    "knowledge.upload",
    "agent.write",
    "agent.test",
    "tool.write",
    "tool.test",
    "plugin.install",
    "plugin.uninstall",
    "plugin.test",
}

ADMIN_PERMISSIONS = EDITOR_PERMISSIONS | {
    "member.invite",
    "member.update",
    "member.remove",
    "model.manage",
    "secret.manage",
    "audit.read",
    "apikey.manage",
    "settings.update",
}

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "viewer": READ_ONLY,
    "runner": RUNNER_PERMISSIONS,
    "editor": EDITOR_PERMISSIONS,
    "admin": ADMIN_PERMISSIONS,
    "owner": {"*"},
}

ROLE_INFO: list[dict[str, Any]] = [
    {
        "id": "owner",
        "name": "所有者",
        "description": "拥有工作空间全部权限，可管理成员、模型、密钥和工作空间设置。",
        "color": "amber",
        "highlights": ["全部资源与设置", "成员与角色管理", "转让/删除工作空间"],
    },
    {
        "id": "admin",
        "name": "管理员",
        "description": "管理工作流、知识库、Agent、工具、模型凭据和成员，但不能修改所有者。",
        "color": "indigo",
        "highlights": ["管理资源与成员", "管理模型与密钥", "查看审计日志"],
    },
    {
        "id": "editor",
        "name": "编辑者",
        "description": "创建和编辑应用、工作流、知识库与 Agent，可运行和发布，但不能管理成员和凭据。",
        "color": "sky",
        "highlights": ["创建/编辑/发布", "上传知识库", "安装插件与工具"],
    },
    {
        "id": "runner",
        "name": "运行者",
        "description": "可以运行已发布工作流、查看运行记录并处理审批，不能修改配置。",
        "color": "emerald",
        "highlights": ["运行工作流", "查看执行轨迹", "处理审批"],
    },
    {
        "id": "viewer",
        "name": "查看者",
        "description": "只读访问工作流、运行记录、知识库与 Agent 配置，不能修改或运行。",
        "color": "slate",
        "highlights": ["只读浏览", "查看运行结果", "无修改权限"],
    },
]

ROLE_BY_ID = {item["id"]: item for item in ROLE_INFO}


def has_permission(principal: Principal, permission: str) -> bool:
    permissions = ROLE_PERMISSIONS.get(principal.role, set())
    if "*" in permissions:
        return True
    if principal.is_api_key and "run" in principal.scopes:
        return permission in RUNNER_PERMISSIONS
    return permission in permissions


def permissions_for_role(role: str) -> list[str]:
    values = ROLE_PERMISSIONS.get(role, set())
    return sorted(ALL_PERMISSIONS if "*" in values else values)


def role_payload(role: str) -> dict[str, Any]:
    info = ROLE_BY_ID.get(role, ROLE_BY_ID["viewer"])
    return {
        **info,
        "role": info["id"],
        "permissions": permissions_for_role(role),
    }


def permission_payload(role: str) -> dict[str, Any]:
    info = ROLE_BY_ID.get(role, ROLE_BY_ID["viewer"])
    if role == "owner":
        invitable = ["admin", "editor", "runner", "viewer"]
    elif role == "admin":
        invitable = ["editor", "runner", "viewer"]
    else:
        invitable = []
    return {
        "role": role,
        "role_name": info["name"],
        "permissions": permissions_for_role(role),
        "roles": [role_payload(item["id"]) for item in ROLE_INFO],
        "can_manage_members": has_permission(
            Principal(user_id=None, tenant_id="", role=role, scopes=[], auth_type="jwt"),
            "member.update",
        ),
        "invitable_roles": invitable,
    }


def permission_for_route(method: str, path: str) -> str | None:
    parts = [part for part in path.split("/") if part]
    if len(parts) < 5 or parts[:3] != ["api", "v1", "tenants"]:
        return None
    resource = parts[4]
    rest = parts[5:]
    method = method.upper()

    if resource == "workflows":
        if method == "GET":
            return "workflow.read"
        if not rest:
            return "workflow.create"
        if rest[0] == "templates":
            return "workflow.create" if method == "POST" else "workflow.read"
        if rest[-1] == "publish":
            return "workflow.publish"
        if rest[-1] == "runs":
            return "workflow.run"
        if rest[-1] == "validate":
            return "workflow.read"
        if "webhooks" in rest or "schedules" in rest:
            return "workflow.run" if rest[-1] == "test" else "workflow.update"
        if method == "DELETE":
            return "workflow.delete"
        if method in {"PATCH", "PUT"}:
            return "workflow.update"
        return "workflow.read"
    if resource == "runs":
        if method == "GET":
            return "run.read"
        if rest and rest[-1] == "cancel":
            return "run.cancel"
        if rest and rest[-1] == "retry":
            return "run.retry"
        return "run.read"
    if resource == "approvals":
        return "approval.decide" if method == "POST" else "approval.read"
    if resource == "knowledge-bases":
        if method == "GET":
            return "knowledge.read"
        if rest and rest[-1] == "search":
            return "knowledge.read"
        if "upload" in rest:
            return "knowledge.upload"
        return "knowledge.write"
    if resource == "agent-sessions":
        return "agent.read" if method == "GET" else "agent.run"
    if resource == "plugins":
        if method == "GET":
            return "plugin.read"
        if method == "DELETE":
            return "plugin.uninstall"
        if rest and rest[-1] == "test":
            return "plugin.test"
        return "plugin.install"
    if resource == "tools":
        if method == "GET":
            return "tool.read"
        if rest and rest[-1] == "test":
            return "tool.test"
        return "tool.write"
    if resource == "mcp-servers":
        return "tool.read" if method == "GET" else "tool.write"
    if resource == "agent-profiles":
        if method == "GET":
            return "agent.read"
        if rest and rest[-1] == "test":
            return "agent.test"
        return "agent.write"
    if resource == "model-profiles":
        if method == "GET":
            return "model.read"
        return "model.manage"
    if resource == "secrets":
        return "secret.manage"
    if resource == "members":
        if method == "GET":
            return "member.read"
        if method == "DELETE":
            return "member.remove"
        return "member.update"
    if resource == "invitations":
        return "member.invite"
    if resource == "audit":
        return "audit.read"
    if resource == "usage":
        return "usage.read"
    if resource == "api-keys":
        return "apikey.manage"
    if resource == "settings":
        return "settings.read" if method == "GET" else "settings.update"
    return None


async def authorize_tenant_request(
    request: Request,
    principal: Principal = Depends(require_tenant),
) -> Principal:
    permission = permission_for_route(request.method, request.url.path)
    if permission and not has_permission(principal, permission):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "permission_denied",
                "permission": permission,
                "role": principal.role,
                "message": "当前角色没有执行此操作的权限",
            },
        )
    return principal
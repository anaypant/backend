"""Register built-in tools by stable id."""

from __future__ import annotations

from typing import Any, Callable

from state.execution_policy import volatile_external_allowed
from tools import db_profile, integration_outbound

ToolFn = Callable[..., tuple[dict, int]]

_REGISTRY: dict[str, ToolFn] = {
    "db.merge_realtor_profile": db_profile.merge_realtor_profile,
    "integration.apply_followupboss_outbound": integration_outbound.apply_followupboss_outbound,
}

# Tools not listed default to volatile_external=True (blocked in analytical mode).
TOOL_META: dict[str, dict[str, bool]] = {
    "db.merge_realtor_profile": {"volatile_external": False},
    "integration.apply_followupboss_outbound": {"volatile_external": True},
}


def tool_meta(tool_id: str) -> dict[str, bool]:
    m = TOOL_META.get(tool_id)
    if m is None:
        return {"volatile_external": True}
    return dict(m)


def get_tool(name: str) -> ToolFn | None:
    return _REGISTRY.get(name)


def run_tool(
    name: str,
    args: dict[str, Any],
    *,
    acting_uid: str,
    acs: dict | None = None,
) -> tuple[dict, int]:
    fn = get_tool(name)
    if fn is None:
        return {"error": f"unknown tool: {name}"}, 400

    meta = tool_meta(name)
    if meta.get("volatile_external"):
        if acs is None:
            return {"error": "acs_required_for_volatile_tool", "tool": name}, 400
        if not volatile_external_allowed(acs):
            return {
                "error": "tool_blocked_by_execution_policy",
                "tool": name,
                "detail": "volatile_external_not_allowed",
            }, 403
    if name == "db.merge_realtor_profile":
        data = args.get("data")
        if not isinstance(data, dict):
            return {"error": "args.data object required"}, 400
        uid = args.get("uid") or acting_uid
        if not isinstance(uid, str):
            return {"error": "args.uid must be a string when provided"}, 400
        return fn(uid.strip(), data)
    if name == "integration.apply_followupboss_outbound":
        uid = args.get("uid") or acting_uid
        if not isinstance(uid, str):
            return {"error": "args.uid must be a string when provided"}, 400
        actions = args.get("actions")
        if not isinstance(actions, list):
            return {"error": "args.actions list required"}, 400
        return fn(uid.strip(), actions)
    return {"error": "tool dispatch not implemented"}, 500

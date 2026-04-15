"""Register built-in tools by stable id."""

from __future__ import annotations

from typing import Any, Callable

from tools import db_profile

ToolFn = Callable[..., tuple[dict, int]]

_REGISTRY: dict[str, ToolFn] = {
    "db.merge_realtor_profile": db_profile.merge_realtor_profile,
}


def get_tool(name: str) -> ToolFn | None:
    return _REGISTRY.get(name)


def run_tool(
    name: str,
    args: dict[str, Any],
    *,
    acting_uid: str,
) -> tuple[dict, int]:
    fn = get_tool(name)
    if fn is None:
        return {"error": f"unknown tool: {name}"}, 400
    if name == "db.merge_realtor_profile":
        data = args.get("data")
        if not isinstance(data, dict):
            return {"error": "args.data object required"}, 400
        uid = args.get("uid") or acting_uid
        if not isinstance(uid, str):
            return {"error": "args.uid must be a string when provided"}, 400
        return fn(uid.strip(), data)
    return {"error": "tool dispatch not implemented"}, 500

"""
Optional HTTP helpers for local / non-prod testing of workflows and tools.

Enable on core-run only with ``ACS_ENABLE_DEV_LAB=1`` (set via Terraform ``enable_core_dev_lab`` or manually).
Requests use a top-level marker on the same POST body shape as ``/core/v1/run`` — never put these keys inside
``state`` sent to real workflows.
"""

from __future__ import annotations

import os
from typing import Any

from tools import registry as tool_registry
from workflows import registry as wf_registry


def dev_lab_enabled() -> bool:
    return (os.environ.get("ACS_ENABLE_DEV_LAB") or "").strip().lower() in ("1", "true", "yes")


def try_dev_lab_response(body: dict[str, Any]) -> tuple[dict[str, Any], int] | None:
    """
    If ``body`` is a dev-lab control request, return ``(payload, http_status)``.
    Otherwise return ``None`` so the normal core handler can run.
    """
    marker = body.get("__ACS_DEV_LAB__")
    if marker not in ("catalog", "run_tool", "run_unit_checks"):
        return None

    if not dev_lab_enabled():
        # 501 (not 403): avoids confusion with Firebase/ESP "forbidden" and execution-policy denials.
        return (
            {
                "error": "dev_lab_disabled",
                "hint": "Set ACS_ENABLE_DEV_LAB=1 on core-run (root Terraform variable enable_core_dev_lab; null defaults to on when environment is dev).",
            },
            501,
        )

    if marker == "catalog":
        return _catalog_payload(), 200

    if marker == "run_unit_checks":
        acting_uid = body.get("acting_uid")
        if not isinstance(acting_uid, str) or not acting_uid.strip():
            return {"error": "acting_uid string required"}, 400
        _ = acting_uid.strip()
        from qa.unit_checks import run_all_unit_checks

        payload = run_all_unit_checks()
        return payload, 200

    # run_tool
    tool_id = body.get("tool_id")
    if not isinstance(tool_id, str) or not tool_id.strip():
        return {"error": "tool_id string required"}, 400
    args = body.get("args")
    if not isinstance(args, dict):
        return {"error": "args object required"}, 400
    acting_uid = body.get("acting_uid")
    if not isinstance(acting_uid, str) or not acting_uid.strip():
        return {"error": "acting_uid string required"}, 400

    acs = body.get("acs")
    if acs is not None and not isinstance(acs, dict):
        return {"error": "acs must be an object when provided"}, 400

    result, st = tool_registry.run_tool(
        tool_id.strip(),
        args,
        acting_uid=acting_uid.strip(),
        acs=acs if isinstance(acs, dict) else None,
    )
    return {"tool_id": tool_id.strip(), "http_status": st, "result": result}, 200


def _catalog_payload() -> dict[str, Any]:
    workflows: list[dict[str, Any]] = []
    for wid in wf_registry.list_registered_workflow_ids():
        workflows.append(
            {
                "id": wid,
                "caps": wf_registry.workflow_caps(wid),
            }
        )
    tools: list[dict[str, Any]] = []
    for tid in tool_registry.list_tool_ids():
        tools.append(
            {
                "id": tid,
                "meta": tool_registry.tool_meta(tid),
            }
        )
    return {
        "ok": True,
        "workflows": workflows,
        "tools": tools,
        "usage": {
            "catalog": 'POST JSON: {"__ACS_DEV_LAB__": "catalog"}',
            "run_tool": (
                'POST JSON: {"__ACS_DEV_LAB__": "run_tool", "tool_id": "...", '
                '"args": {...}, "acting_uid": "...", "acs": {...}?}'
            ),
            "run_workflow": 'POST JSON: {"workflow_id": "contact.enrichment_v1", "state": { ... }} (normal core run)',
            "run_unit_checks": (
                'POST JSON: {"__ACS_DEV_LAB__": "run_unit_checks", "acting_uid": "<firebase-uid>"} '
                "(requires ACS_ENABLE_DEV_LAB=1)"
            ),
        },
    }

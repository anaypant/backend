"""Lab: SSE streaming execution of LangGraph workflows.

Returns a Python generator of SSE-formatted strings.  Each yielded string is one
complete SSE frame (ending with a blank line).  The caller in main.py wraps this
generator in a Flask streaming ``Response``.

Event types
-----------
run_start  : {workflow_id, exec_workflow_id, correlation_id, user_id, started_at_ms, substituted}
node_end   : {node, seq, duration_ms, state_snapshot, errors, audit_extra}
run_end    : {status, duration_ms, billing, node_trail, final_state}
error      : {message, traceback}

All ``data`` fields are JSON-encoded.  The ``state_snapshot`` is the ``acs`` dict at
the moment the node completed, truncated to ``_MAX_STATE_BYTES`` for large payloads.
"""

from __future__ import annotations

import json
import logging
import time
import traceback
import uuid
from typing import Any, Generator

from workflows import registry as wf_registry

_logger = logging.getLogger(__name__)

# Nodes injected by LangGraph that are not real workflow nodes.
_INTERNAL_NODES = {"__start__", "__START__", "__end__", "__END__"}

# Truncate large state snapshots to keep SSE frames reasonable.
_MAX_STATE_BYTES = 48_000


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------


def _sse(event_type: str, data: dict[str, Any]) -> str:
    """Serialise one SSE frame: ``event: …\\ndata: …\\n\\n``."""
    try:
        payload = json.dumps(data, default=str)
    except Exception:
        payload = json.dumps({"_serialization_error": True})
    return f"event: {event_type}\ndata: {payload}\n\n"


def _keepalive() -> str:
    """SSE comment line — keeps the connection alive without emitting a named event."""
    return ": keepalive\n\n"


def _truncate_state(acs: dict) -> dict:
    """
    Return a JSON-safe snapshot of *acs* that fits within ``_MAX_STATE_BYTES``.

    Strategy: try the full object first; if it's too large, replace oversized
    leaf dicts/lists with a ``"<type N chars>"`` sentinel so the top-level
    structure is still visible.
    """
    try:
        raw = json.dumps(acs, default=str)
        if len(raw) <= _MAX_STATE_BYTES:
            return acs
    except Exception:
        return {}

    try:
        trimmed: dict[str, Any] = {}
        for k, v in acs.items():
            try:
                v_str = json.dumps(v, default=str)
            except Exception:
                trimmed[k] = "<unserializable>"
                continue
            if len(v_str) <= 4_000:
                trimmed[k] = v
            else:
                trimmed[k] = f"<{type(v).__name__} {len(v_str)} chars — truncated>"
        return trimmed
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Audit extraction helpers
# ---------------------------------------------------------------------------


def _latest_audit_entry_for_node(acs: dict, node_name: str) -> dict[str, Any]:
    """Return the most recent ``workflowAudit.nodes`` entry for *node_name*."""
    meta = acs.get("metadata") if isinstance(acs.get("metadata"), dict) else {}
    wa = meta.get("workflowAudit") if isinstance(meta.get("workflowAudit"), dict) else {}
    nodes_log = wa.get("nodes") if isinstance(wa.get("nodes"), list) else []
    for entry in reversed(nodes_log):
        if isinstance(entry, dict) and entry.get("node") == node_name:
            return entry
    return {}


def _billing_from_acs(acs: dict) -> dict[str, Any]:
    meta = acs.get("metadata") if isinstance(acs.get("metadata"), dict) else {}
    wa = meta.get("workflowAudit") if isinstance(meta.get("workflowAudit"), dict) else {}
    billing = wa.get("billing")
    return billing if isinstance(billing, dict) else {}


def _core_status_from_acs(acs: dict) -> str | None:
    meta = acs.get("metadata") if isinstance(acs.get("metadata"), dict) else {}
    core = meta.get("core") if isinstance(meta.get("core"), dict) else {}
    s = core.get("status")
    return s if isinstance(s, str) else None


# ---------------------------------------------------------------------------
# Main streaming generator
# ---------------------------------------------------------------------------


def stream_workflow_run(
    workflow_id: str,
    state: dict[str, Any],
    *,
    correlation_id: str | None = None,
) -> Generator[str, None, None]:
    """
    Yield SSE frames for a complete workflow run.

    The generator drives ``graph.stream()`` (LangGraph) and emits one
    ``node_end`` event per node as it completes, bookended by ``run_start``
    and ``run_end``.  All exceptions are caught and emitted as ``error`` events
    so the client can display them rather than seeing a bare connection drop.
    """
    if not wf_registry.is_registered(workflow_id):
        yield _sse("error", {"message": f"unknown workflow_id: {workflow_id}"})
        return

    # Prepare state
    out_state: dict[str, Any] = dict(state)
    if not correlation_id:
        correlation_id = out_state.get("correlation_id") or str(uuid.uuid4())
    out_state.setdefault("correlation_id", correlation_id)

    # Policy substitution (e.g. volatile → analytical stub)
    try:
        exec_workflow_id = wf_registry.resolve_registered_workflow_id(
            workflow_id, out_state
        )
    except Exception as exc:
        yield _sse("error", {"message": f"workflow resolution failed: {exc}"})
        return

    graph = wf_registry._GRAPHS.get(exec_workflow_id)
    if graph is None:
        yield _sse("error", {"message": f"graph not found: {exec_workflow_id}"})
        return

    run_start_ms = int(time.time() * 1000)
    yield _sse(
        "run_start",
        {
            "workflow_id": workflow_id,
            "exec_workflow_id": exec_workflow_id,
            "correlation_id": correlation_id,
            "user_id": out_state.get("user_id"),
            "started_at_ms": run_start_ms,
            "substituted": exec_workflow_id != workflow_id,
        },
    )

    # --- streaming execution ---
    seq = 0
    node_trail: list[str] = []
    final_acs: dict[str, Any] = out_state
    status = "completed"
    node_start_wall: float = time.perf_counter()

    try:
        for chunk in graph.stream({"acs": out_state}, stream_mode="updates"):
            # chunk == {node_name: {updated_key: value, ...}}
            if not isinstance(chunk, dict):
                continue

            for node_name, node_updates in chunk.items():
                if node_name in _INTERNAL_NODES:
                    continue

                node_end_wall = time.perf_counter()
                elapsed_ms = round((node_end_wall - node_start_wall) * 1000, 2)
                node_start_wall = node_end_wall

                # Update final_acs with this node's acs output
                if isinstance(node_updates, dict) and "acs" in node_updates:
                    final_acs = node_updates["acs"]

                # Prefer timing from workflow_audit if present (more precise)
                audit_entry = _latest_audit_entry_for_node(final_acs, node_name)
                audit_duration = audit_entry.get("duration_ms")
                duration_ms = (
                    float(audit_duration) if isinstance(audit_duration, (int, float))
                    else elapsed_ms
                )
                audit_extra = audit_entry.get("extra") or {}

                errors: list[Any] = []
                if isinstance(final_acs, dict):
                    raw_errors = final_acs.get("errors")
                    if isinstance(raw_errors, list):
                        # Only show errors accumulated so far, last 20
                        errors = raw_errors[-20:]

                seq += 1
                node_trail.append(node_name)

                yield _sse(
                    "node_end",
                    {
                        "node": node_name,
                        "seq": seq,
                        "duration_ms": duration_ms,
                        "state_snapshot": _truncate_state(final_acs),
                        "errors": errors,
                        "audit_extra": audit_extra,
                    },
                )

    except Exception as exc:
        tb = traceback.format_exc()
        _logger.exception(
            "lab_stream: exception in workflow workflow_id=%s correlation_id=%s",
            workflow_id,
            correlation_id,
        )
        status = "error"
        yield _sse(
            "error",
            {
                "message": str(exc),
                "traceback": tb[-4_000:],
            },
        )

    # Determine final status from core metadata if set by the workflow
    if status == "completed":
        core_status = _core_status_from_acs(final_acs)
        if core_status == "failed":
            status = "failed"

    billing = _billing_from_acs(final_acs)
    run_end_ms = int(time.time() * 1000)

    yield _sse(
        "run_end",
        {
            "status": status,
            "duration_ms": run_end_ms - run_start_ms,
            "billing": billing,
            "node_trail": node_trail,
            "final_state": _truncate_state(final_acs),
        },
    )

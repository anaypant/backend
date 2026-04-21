"""Per-run workflow audit: timing, node logs, and LLM usage counters (billing hooks)."""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from state import acs_state

_logger = logging.getLogger(__name__)


def _correlation_id(acs: dict) -> str:
    c = acs.get("correlation_id")
    return c.strip() if isinstance(c, str) and c.strip() else ""


def _extra_for_log(extra: dict[str, Any] | None) -> str:
    if not extra:
        return "{}"
    try:
        s = json.dumps(extra, default=str, sort_keys=True)
    except TypeError:
        s = str(extra)
    if len(s) > 800:
        return s[:800] + "...[truncated]"
    return s


def _audit_bucket(acs: dict) -> dict[str, Any]:
    meta = acs_state.ensure_metadata(acs)
    cur = meta.get("workflowAudit")
    if not isinstance(cur, dict):
        cur = {
            "run_id": str(uuid.uuid4()),
            "nodes": [],
            "billing": {"llm_calls": 0, "llm_tokens_reported": None, "db_reads": 0, "db_queries": 0},
        }
        meta["workflowAudit"] = cur
    return cur


def audit_run_start(acs: dict, workflow_id: str) -> None:
    a = _audit_bucket(acs)
    a["workflow_id"] = workflow_id
    a["started_at_epoch_ms"] = int(time.time() * 1000)
    _logger.info(
        "workflow_audit run_start workflow_id=%s correlation_id=%s user_id=%s",
        workflow_id,
        _correlation_id(acs),
        acs.get("user_id") if isinstance(acs.get("user_id"), str) else "",
    )


def audit_run_finish(acs: dict, *, status: str, detail: str | None = None) -> None:
    a = _audit_bucket(acs)
    a["finished_at_epoch_ms"] = int(time.time() * 1000)
    start = a.get("started_at_epoch_ms")
    if isinstance(start, int):
        a["duration_ms"] = a["finished_at_epoch_ms"] - start
    a["status"] = status
    if detail:
        a["detail"] = detail
    nodes = a.get("nodes")
    n_nodes = len(nodes) if isinstance(nodes, list) else 0
    b = a.get("billing") if isinstance(a.get("billing"), dict) else {}
    _logger.info(
        "workflow_audit run_finish workflow_id=%s correlation_id=%s status=%s detail=%s duration_ms=%s node_count=%s billing=%s",
        a.get("workflow_id"),
        _correlation_id(acs),
        status,
        detail or "",
        a.get("duration_ms"),
        n_nodes,
        _extra_for_log(b if isinstance(b, dict) else None),
    )


def audit_log_node(
    acs: dict,
    node: str,
    *,
    duration_ms: float | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    a = _audit_bucket(acs)
    nodes = a.get("nodes")
    if not isinstance(nodes, list):
        nodes = []
        a["nodes"] = nodes
    entry: dict[str, Any] = {"node": node, "at_epoch_ms": int(time.time() * 1000)}
    if duration_ms is not None:
        entry["duration_ms"] = round(duration_ms, 3)
    if extra:
        entry["extra"] = extra
    nodes.append(entry)
    _logger.info(
        "workflow_audit node=%s correlation_id=%s duration_ms=%s extra=%s",
        node,
        _correlation_id(acs),
        round(duration_ms, 3) if duration_ms is not None else None,
        _extra_for_log(extra),
    )


def audit_bump_llm(acs: dict) -> None:
    a = _audit_bucket(acs)
    b = a.get("billing")
    if not isinstance(b, dict):
        b = {}
        a["billing"] = b
    n = b.get("llm_calls")
    b["llm_calls"] = (int(n) + 1) if isinstance(n, int) else 1


def audit_bump_db_read(acs: dict, n: int = 1) -> None:
    a = _audit_bucket(acs)
    b = a.get("billing")
    if not isinstance(b, dict):
        b = {}
        a["billing"] = b
    cur = b.get("db_reads")
    b["db_reads"] = (int(cur) + n) if isinstance(cur, int) else n


def audit_bump_db_query(acs: dict, n: int = 1) -> None:
    a = _audit_bucket(acs)
    b = a.get("billing")
    if not isinstance(b, dict):
        b = {}
        a["billing"] = b
    cur = b.get("db_queries")
    b["db_queries"] = (int(cur) + n) if isinstance(cur, int) else n

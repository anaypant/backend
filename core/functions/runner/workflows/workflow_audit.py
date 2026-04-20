"""Per-run workflow audit: timing, node logs, and LLM usage counters (billing hooks)."""

from __future__ import annotations

import time
import uuid
from typing import Any

from state import acs_state


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


def audit_run_finish(acs: dict, *, status: str, detail: str | None = None) -> None:
    a = _audit_bucket(acs)
    a["finished_at_epoch_ms"] = int(time.time() * 1000)
    start = a.get("started_at_epoch_ms")
    if isinstance(start, int):
        a["duration_ms"] = a["finished_at_epoch_ms"] - start
    a["status"] = status
    if detail:
        a["detail"] = detail


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

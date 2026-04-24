"""Lab: graph topology extraction from compiled LangGraph graphs.

Exposes node/edge structure for frontend DAG visualization via GET /core/v1/lab/graphs
and GET /core/v1/lab/graph/{workflow_id}.
"""

from __future__ import annotations

import logging
from typing import Any

from workflows.registry import _GRAPHS, list_registered_workflow_ids, workflow_caps

_logger = logging.getLogger(__name__)

# Node IDs used by LangGraph for entry/exit; excluded from product UI or rendered as terminals.
_START_IDS = {"__start__", "__START__"}
_END_IDS = {"__end__", "__END__", "END"}


def _node_kind(node_id: str) -> str:
    if node_id in _START_IDS:
        return "start"
    if node_id in _END_IDS:
        return "end"
    return "node"


def get_graph_topology(workflow_id: str) -> dict[str, Any]:
    """Return JSON-serialisable topology (nodes + edges) for one workflow."""
    graph = _GRAPHS.get(workflow_id)
    if graph is None:
        raise KeyError(f"unknown workflow_id: {workflow_id}")

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    try:
        drawable = graph.get_graph()

        for nid, node in drawable.nodes.items():
            label = nid
            if hasattr(node, "name") and node.name:
                label = node.name
            nodes.append(
                {
                    "id": nid,
                    "label": label,
                    "kind": _node_kind(nid),
                }
            )

        for edge in drawable.edges:
            conditional = bool(getattr(edge, "conditional", False))
            label_raw = getattr(edge, "data", None)
            label = str(label_raw) if label_raw else None
            edges.append(
                {
                    "source": edge.source,
                    "target": edge.target,
                    "conditional": conditional,
                    "label": label,
                }
            )
    except Exception as exc:
        _logger.warning(
            "lab_graph: get_graph() failed for workflow_id=%s: %s", workflow_id, exc
        )

    return {
        "workflow_id": workflow_id,
        "nodes": nodes,
        "edges": edges,
        "caps": workflow_caps(workflow_id),
    }


def list_topologies() -> list[dict[str, Any]]:
    """Return topology for every registered workflow (sorted by id)."""
    result = []
    for wid in list_registered_workflow_ids():
        try:
            result.append(get_graph_topology(wid))
        except Exception as exc:
            _logger.warning("lab_graph: list_topologies skip %s: %s", wid, exc)
    return result

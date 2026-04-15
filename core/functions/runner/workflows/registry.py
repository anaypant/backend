"""Maps workflow_id to compiled LangGraph callables."""

from __future__ import annotations

from typing import Any, Callable

from workflows import demo_joke_to_profile

_Runner = Callable[[dict], dict]

_GRAPHS: dict[str, Any] = {
    "demo.joke_to_profile_v1": demo_joke_to_profile.build_demo_joke_graph(),
}


def run_workflow(workflow_id: str, acs: dict) -> dict:
    graph = _GRAPHS.get(workflow_id)
    if graph is None:
        raise KeyError(f"unknown workflow_id: {workflow_id}")
    out: dict = graph.invoke({"acs": acs})
    return out.get("acs") if isinstance(out, dict) else acs


def is_registered(workflow_id: str) -> bool:
    return workflow_id in _GRAPHS

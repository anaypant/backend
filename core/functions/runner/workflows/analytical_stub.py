"""Minimal workflow when a volatile-external workflow is skipped in analytical mode."""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from state import acs_state


class AnalyticalStubState(TypedDict, total=False):
    acs: dict[str, Any]


def _node_stub(state: AnalyticalStubState) -> dict[str, Any]:
    acs: dict = state["acs"]
    acs_state.set_core_meta(
        acs,
        {
            "workflow_id": "analytical.stub_v1",
            "status": "completed",
            "phase": "stub",
            "note": "volatile_workflow_skipped_in_analytical_mode",
        },
    )
    return {"acs": acs}


def build_analytical_stub_graph():
    g = StateGraph(AnalyticalStubState)
    g.add_node("stub", _node_stub)
    g.set_entry_point("stub")
    g.add_edge("stub", END)
    return g.compile()

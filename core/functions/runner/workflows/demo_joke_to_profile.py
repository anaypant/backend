"""demo.joke_to_profile_v1 — LLM joke then merge into realtor profile."""

from __future__ import annotations

import logging
import os
import time
from typing import Any, TypedDict

_logger = logging.getLogger(__name__)

from langgraph.graph import END, StateGraph

from clients import integration_bridge, llm_internal
from state import acs_state
from state.execution_policy import integration_maintenance_allowed
from tools import registry as tool_registry


class DemoState(TypedDict, total=False):
    acs: dict[str, Any]
    joke: str
    failed: bool


def _default_llm_provider() -> str:
    return (os.environ.get("ACS_DEMO_LLM_PROVIDER") or "openrouter").strip() or "openrouter"


def _default_llm_model() -> str:
    return (os.environ.get("ACS_DEMO_LLM_MODEL") or "openai/gpt-4o-mini").strip() or "openai/gpt-4o-mini"


def _node_generate_joke(state: DemoState) -> dict[str, Any]:
    acs: dict = state["acs"]
    _logger.info(
        "demo.joke_to_profile_v1 node=generate_joke correlation_id=%s user_id=%s",
        acs.get("correlation_id"),
        acs.get("user_id"),
    )
    uid = acs.get("user_id")
    if not isinstance(uid, str) or not uid.strip():
        acs_state.append_error(acs, "user_id missing on state; cannot run demo workflow")
        acs_state.set_core_meta(acs, {"workflow_id": "demo.joke_to_profile_v1", "status": "failed", "phase": "llm"})
        return {"acs": acs, "joke": "", "failed": True}

    if (os.environ.get("INTEGRATION_BRIDGE_BASE_URL") or "").strip():
        meta0 = acs_state.ensure_metadata(acs)
        meta0.setdefault("workflowDemo", {})
        if not integration_maintenance_allowed(acs):
            if isinstance(meta0["workflowDemo"], dict):
                meta0["workflowDemo"]["fubPrepareSkipped"] = "integration_maintenance_disabled"
        else:
            prep, pst = integration_bridge.fub_refresh_and_sync_webhooks(uid.strip(), refresh_tokens_first=True)
            if isinstance(meta0["workflowDemo"], dict):
                meta0["workflowDemo"]["fubPrepareHttpStatus"] = pst
            if pst >= 400:
                _logger.warning(
                    "demo.joke_to_profile_v1 fub_prepare failed status=%s body=%s",
                    pst,
                    prep,
                )
                acs_state.append_error(acs, f"fub_prepare (refresh+webhooks) failed: {pst}")

    provider = _default_llm_provider()
    model = _default_llm_model()
    messages = [
        {
            "role": "user",
            "content": "Write one short real-estate-themed joke (one or two sentences).",
        }
    ]
    try:
        body, st = llm_internal.complete(
            model=model,
            messages=messages,
            provider=provider,
            response_format="text",
        )
    except Exception as e:
        acs_state.append_error(acs, f"llm client error: {e!s}")
        acs_state.set_core_meta(acs, {"workflow_id": "demo.joke_to_profile_v1", "status": "failed", "phase": "llm"})
        return {"acs": acs, "joke": "", "failed": True}

    if st >= 400:
        acs_state.append_error(acs, f"llm service returned {st}: {body!r}")
        acs_state.set_core_meta(acs, {"workflow_id": "demo.joke_to_profile_v1", "status": "failed", "phase": "llm"})
        return {"acs": acs, "joke": "", "failed": True}

    text = body.get("text") if isinstance(body.get("text"), str) else ""
    if not text.strip():
        acs_state.append_error(acs, "llm returned empty text")
        acs_state.set_core_meta(acs, {"workflow_id": "demo.joke_to_profile_v1", "status": "failed", "phase": "llm"})
        return {"acs": acs, "joke": "", "failed": True}

    meta = acs_state.ensure_metadata(acs)
    meta.setdefault("workflowDemo", {})
    if isinstance(meta["workflowDemo"], dict):
        meta["workflowDemo"]["lastJokeModel"] = model
        meta["workflowDemo"]["lastJokeProvider"] = provider

    acs_state.set_core_meta(
        acs,
        {
            "workflow_id": "demo.joke_to_profile_v1",
            "phase": "after_llm",
            "llm": {"provider": provider, "model": model, "http_status": st},
        },
    )
    return {"acs": acs, "joke": text.strip(), "failed": False}


def _node_merge_profile(state: DemoState) -> dict[str, Any]:
    acs: dict = state["acs"]
    _logger.info(
        "demo.joke_to_profile_v1 node=merge_profile correlation_id=%s failed=%s",
        acs.get("correlation_id"),
        bool(state.get("failed")),
    )
    if state.get("failed"):
        acs_state.set_core_meta(acs, {"status": "failed", "workflow_id": "demo.joke_to_profile_v1"})
        return {"acs": acs}

    uid = acs.get("user_id")
    joke = state.get("joke") or ""
    if not isinstance(uid, str) or not uid.strip():
        acs_state.append_error(acs, "user_id missing for merge step")
        acs_state.set_core_meta(acs, {"status": "failed", "workflow_id": "demo.joke_to_profile_v1"})
        return {"acs": acs}

    patch = {
        "workflowDemo": {
            "joke": joke,
            "writtenAtEpoch": int(time.time()),
            "workflowId": "demo.joke_to_profile_v1",
        }
    }
    resp, st = tool_registry.run_tool(
        "db.merge_realtor_profile",
        {"data": patch, "uid": uid.strip()},
        acting_uid=uid.strip(),
        acs=acs,
    )
    if st >= 400:
        acs_state.append_error(acs, f"db merge failed: {st} {resp!r}")
        acs_state.set_core_meta(
            acs,
            {"status": "failed", "workflow_id": "demo.joke_to_profile_v1", "phase": "db"},
        )
        return {"acs": acs}

    acs_state.set_core_meta(
        acs,
        {
            "status": "completed",
            "workflow_id": "demo.joke_to_profile_v1",
            "db": {"http_status": st},
        },
    )
    return {"acs": acs}


def build_demo_joke_graph():
    g = StateGraph(DemoState)
    g.add_node("generate_joke", _node_generate_joke)
    g.add_node("merge_profile", _node_merge_profile)
    g.set_entry_point("generate_joke")
    g.add_edge("generate_joke", "merge_profile")
    g.add_edge("merge_profile", END)
    return g.compile()

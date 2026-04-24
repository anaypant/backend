"""Maps workflow_id to compiled LangGraph callables."""

from __future__ import annotations

from typing import Any, Callable

from state import acs_state
from state.execution_policy import get_execution_policy
from workflows import (
    analytical_stub,
    appointment_prep_v1,
    auto_reply_v1,
    ads_management_v1,
    contact_enrichment_v1,
    demo_joke_to_profile,
    drip_campaign_v1,
    hot_leads_v1,
    lead_scoring_v1,
)
from workflows.migrations import import_leads_v1

_Runner = Callable[[dict], dict]

_GRAPHS: dict[str, Any] = {
    "demo.joke_to_profile_v1": demo_joke_to_profile.build_demo_joke_graph(),
    "analytical.stub_v1": analytical_stub.build_analytical_stub_graph(),
    "contact.enrichment_v1": contact_enrichment_v1.build_contact_enrichment_graph(),
    "migration.import_leads_v1": import_leads_v1.build_import_leads_graph(),
    # Glyde workflows
    "appointment.prep_v1": appointment_prep_v1.build_appointment_prep_graph(),
    "lead.scoring_v1": lead_scoring_v1.build_lead_scoring_graph(),
    "communication.auto_reply_v1": auto_reply_v1.build_auto_reply_graph(),
    "campaign.drip_v1": drip_campaign_v1.build_drip_campaign_graph(),
    "ads.management_v1": ads_management_v1.build_ads_management_graph(),
    "lead.hot_notify_v1": hot_leads_v1.build_hot_leads_graph(),
}

# Unknown registered ids should not happen; unlisted workflow_ids passed to core are not in _GRAPHS.
# For ids in _GRAPHS, missing entry defaults to volatile_external=True (safe).
WORKFLOW_CAPS: dict[str, dict[str, bool]] = {
    "demo.joke_to_profile_v1": {
        "volatile_external": False,
        "requires_integration_maintenance": True,
    },
    "analytical.stub_v1": {
        "volatile_external": False,
        "requires_integration_maintenance": False,
    },
    "contact.enrichment_v1": {
        "volatile_external": False,
        "requires_integration_maintenance": False,
    },
    "migration.import_leads_v1": {
        "volatile_external": False,
        "requires_integration_maintenance": False,
    },
    # Glyde workflow caps
    "appointment.prep_v1": {
        "volatile_external": False,
        "requires_integration_maintenance": False,
    },
    "lead.scoring_v1": {
        "volatile_external": False,
        "requires_integration_maintenance": False,
    },
    "communication.auto_reply_v1": {
        # Sends messages; requires explicit realtor opt-in via GlydeSettings.autoReplyEnabled
        "volatile_external": True,
        "requires_integration_maintenance": False,
    },
    "campaign.drip_v1": {
        # Sends campaign messages via FUB; requires volatile_external policy
        "volatile_external": True,
        "requires_integration_maintenance": False,
    },
    "ads.management_v1": {
        # Creates/updates/deletes ads on Google + Meta; requires volatile_external policy
        "volatile_external": True,
        "requires_integration_maintenance": False,
    },
    "lead.hot_notify_v1": {
        # Assist-only: creates notifications, no actions on leads themselves
        "volatile_external": False,
        "requires_integration_maintenance": False,
    },
}


def workflow_caps(workflow_id: str) -> dict[str, bool]:
    caps = WORKFLOW_CAPS.get(workflow_id)
    if caps is None:
        return {"volatile_external": True, "requires_integration_maintenance": False}
    return dict(caps)


def resolve_registered_workflow_id(workflow_id: str, acs: dict) -> str:
    """
    If the requested workflow requires volatile external effects and policy disallows them,
    return ``analytical.stub_v1`` and record routing metadata on ``acs``.
    """
    caps = workflow_caps(workflow_id)
    policy = get_execution_policy(acs)
    if caps.get("volatile_external") and not policy.get("volatile_external_allowed"):
        meta = acs_state.ensure_metadata(acs)
        wr = meta.get("workflow_routing")
        if not isinstance(wr, dict):
            wr = {}
        wr.update(
            {
                "requested_workflow_id": workflow_id,
                "substituted_workflow_id": "analytical.stub_v1",
                "reason": "analytical_mode",
            }
        )
        meta["workflow_routing"] = wr
        return "analytical.stub_v1"
    return workflow_id


def run_workflow(workflow_id: str, acs: dict) -> dict:
    graph = _GRAPHS.get(workflow_id)
    if graph is None:
        raise KeyError(f"unknown workflow_id: {workflow_id}")
    out: dict = graph.invoke({"acs": acs})
    return out.get("acs") if isinstance(out, dict) else acs


def is_registered(workflow_id: str) -> bool:
    return workflow_id in _GRAPHS


def list_registered_workflow_ids() -> list[str]:
    """Stable ids for dev UIs and introspection (sorted)."""
    return sorted(_GRAPHS.keys())

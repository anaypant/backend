"""campaign.drip_v1 — run birthday/anniversary drip campaigns with quarantine logic.

Triggered by Cloud Scheduler daily. Iterates all leads eligible for a drip touch,
skips quarantined / recently-contacted leads, personalizes a message via LLM,
and dispatches via FUB outbound actions.

PM v1: ``glydeLeadLane`` (active vs nurture) does not gate drip — only ``glydeQuarantined``
and cooldown/contact rules apply. Lane is used by enrichment/intel cost routing instead.

volatile_external: True — sends messages; requires execution_policy to allow it.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import time
import uuid
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from clients import db_internal, llm_internal
from state import acs_state
from state.execution_policy import volatile_external_allowed
from workflows import workflow_audit

_logger = logging.getLogger(__name__)

_WORKFLOW_ID = "campaign.drip_v1"
_DEFAULT_COOLDOWN_DAYS = 30
_MAX_LEADS_PER_RUN = 50


class DripCampaignState(TypedDict, total=False):
    acs: dict[str, Any]
    failed: bool
    glyde_settings: dict[str, Any]
    realtor_profile: dict[str, Any]
    eligible_leads: list[dict[str, Any]]
    messages_queued: list[dict[str, Any]]
    messages_sent: int


def _uid(acs: dict) -> str | None:
    u = acs.get("user_id")
    return u.strip() if isinstance(u, str) and u.strip() else None


def _iso_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _today() -> datetime.date:
    return datetime.date.today()


def _days_since(date_str: str | None) -> int | None:
    if not date_str:
        return None
    try:
        dt = datetime.datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        delta = datetime.datetime.now(datetime.timezone.utc) - dt.astimezone(datetime.timezone.utc)
        return max(0, delta.days)
    except (ValueError, TypeError):
        return None


def _is_birthday_today(lead: dict[str, Any]) -> bool:
    bday = lead.get("birthday") or lead.get("birthDate") or lead.get("dateOfBirth")
    if not bday:
        return False
    try:
        bd = datetime.date.fromisoformat(str(bday)[:10])
        today = _today()
        return bd.month == today.month and bd.day == today.day
    except (ValueError, TypeError):
        return False


def _is_home_anniversary_today(lead: dict[str, Any]) -> bool:
    close_date = lead.get("closingDate") or lead.get("homeAnniversary") or lead.get("moveInDate")
    if not close_date:
        return False
    try:
        cd = datetime.date.fromisoformat(str(close_date)[:10])
        today = _today()
        return cd.month == today.month and cd.day == today.day and cd.year < today.year
    except (ValueError, TypeError):
        return False


def _node_load_settings(state: DripCampaignState) -> dict[str, Any]:
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    workflow_audit.audit_run_start(acs, _WORKFLOW_ID)

    uid = _uid(acs)
    if not uid:
        acs_state.append_error(acs, "user_id missing")
        acs_state.set_core_meta(acs, {"workflow_id": _WORKFLOW_ID, "status": "failed", "phase": "load_settings"})
        return {"acs": acs, "failed": True}

    profile_body, _ = db_internal.read_document(f"Realtors/{uid}", acting_uid=uid)
    workflow_audit.audit_bump_db_read(acs)
    profile = profile_body.get("data") if isinstance(profile_body.get("data"), dict) else {}

    settings_body, _ = db_internal.read_document(f"Realtors/{uid}/GlydeSettings/config", acting_uid=uid)
    workflow_audit.audit_bump_db_read(acs)
    settings = settings_body.get("data") if isinstance(settings_body.get("data"), dict) else {}

    workflow_audit.audit_log_node(acs, "load_settings", duration_ms=(time.perf_counter() - t0) * 1000)
    return {"acs": acs, "failed": False, "realtor_profile": profile, "glyde_settings": settings}


def _node_query_eligible_leads(state: DripCampaignState) -> dict[str, Any]:
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    if state.get("failed"):
        return {"acs": acs}

    uid = _uid(acs)
    if not uid:
        return {"acs": acs, "eligible_leads": []}

    leads_body, lst = db_internal.query_collection(
        f"Realtors/{uid}/Leads",
        filters=[{"field": "ownerUid", "op": "==", "value": uid}],
        acting_uid=uid,
        limit=200,
    )
    workflow_audit.audit_bump_db_query(acs)

    all_leads: list[dict] = []
    if lst == 200 and isinstance(leads_body.get("items"), list):
        for item in leads_body["items"]:
            data = item.get("data") if isinstance(item.get("data"), dict) else {}
            if data:
                all_leads.append(data)

    today = _today()
    eligible: list[dict[str, Any]] = []
    for lead in all_leads:
        lead_data = lead.get("lead") if isinstance(lead.get("lead"), dict) else lead
        reason = None
        if _is_birthday_today(lead_data):
            reason = "birthday"
        elif _is_home_anniversary_today(lead_data):
            reason = "home_anniversary"
        if reason:
            eligible.append({"lead": lead_data, "trigger": reason, "canonicalLeadId": lead.get("canonicalLeadId") or lead.get("id") or ""})

    workflow_audit.audit_log_node(
        acs,
        "query_eligible_leads",
        duration_ms=(time.perf_counter() - t0) * 1000,
        extra={"total": len(all_leads), "eligible": len(eligible), "date": today.isoformat()},
    )
    return {"acs": acs, "eligible_leads": eligible[:_MAX_LEADS_PER_RUN]}


def _node_quarantine_filter(state: DripCampaignState) -> dict[str, Any]:
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    if state.get("failed"):
        return {"acs": acs}

    settings = state.get("glyde_settings") or {}
    cooldown_days = int(settings.get("dripCooldownDays") or _DEFAULT_COOLDOWN_DAYS)
    eligible = state.get("eligible_leads") or []

    filtered: list[dict[str, Any]] = []
    skipped = 0
    for item in eligible:
        lead = item.get("lead") or {}
        if lead.get("glydeQuarantined"):
            skipped += 1
            continue
        last_drip = lead.get("glydeDripLastSentAt")
        days_ago = _days_since(last_drip)
        if days_ago is not None and days_ago < cooldown_days:
            skipped += 1
            continue
        filtered.append(item)

    workflow_audit.audit_log_node(
        acs,
        "quarantine_filter",
        duration_ms=(time.perf_counter() - t0) * 1000,
        extra={"before": len(eligible), "after": len(filtered), "skipped": skipped},
    )
    return {"acs": acs, "eligible_leads": filtered}


def _node_personalize_and_send(state: DripCampaignState) -> dict[str, Any]:
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    if state.get("failed"):
        return {"acs": acs, "messages_sent": 0}

    eligible = state.get("eligible_leads") or []
    if not eligible:
        workflow_audit.audit_log_node(acs, "personalize_and_send", duration_ms=(time.perf_counter() - t0) * 1000, extra={"skipped": "no_eligible"})
        return {"acs": acs, "messages_sent": 0, "messages_queued": []}

    uid = _uid(acs)
    realtor = state.get("realtor_profile") or {}
    realtor_name = realtor.get("displayName") or realtor.get("email") or "your agent"

    can_send = volatile_external_allowed(acs)
    actions: list[dict[str, Any]] = []
    queued: list[dict[str, Any]] = []

    for item in eligible:
        lead = item.get("lead") or {}
        trigger = item.get("trigger") or "reminder"
        person_id = lead.get("personId") or lead.get("id") or lead.get("externalId")
        lead_name = lead.get("name") or lead.get("firstName") or "there"

        msg = _generate_drip_message(lead_name, trigger, realtor_name)

        record: dict[str, Any] = {
            "canonicalLeadId": item.get("canonicalLeadId") or "",
            "personId": person_id,
            "trigger": trigger,
            "message": msg,
            "scheduledAt": _iso_now(),
        }
        queued.append(record)

        if can_send and person_id:
            actions.append({
                "name": "createNote",
                "payload": {"personId": person_id, "body": msg, "isOutbound": True},
                "effect": "volatile_external",
            })
            if uid:
                db_internal.upsert_merge(
                    f"Realtors/{uid}/Leads/{item.get('canonicalLeadId') or person_id}",
                    {"glydeDripLastSentAt": _iso_now(), "glydeDripLastTrigger": trigger},
                    acting_uid=uid,
                )

    meta = acs_state.ensure_metadata(acs)
    if actions:
        meta["outboundActions"] = actions

    if uid and queued:
        log_id = str(uuid.uuid4())
        _, _ = db_internal.upsert_merge(
            f"Realtors/{uid}/DripLog/{log_id}",
            {
                "ownerUid": uid,
                "runAt": _iso_now(),
                "count": len(queued),
                "sent": can_send,
                "items": queued[:20],
            },
            acting_uid=uid,
        )

    workflow_audit.audit_bump_llm(acs)
    workflow_audit.audit_log_node(
        acs,
        "personalize_and_send",
        duration_ms=(time.perf_counter() - t0) * 1000,
        extra={"queued": len(queued), "actions": len(actions), "can_send": can_send},
    )
    return {"acs": acs, "messages_queued": queued, "messages_sent": len(actions)}


def _generate_drip_message(lead_name: str, trigger: str, realtor_name: str) -> str:
    """Generate a short personalized drip message without an LLM call for reliability.
    For production, replace with an LLM call to personalize at scale.
    """
    if trigger == "birthday":
        return (
            f"Happy Birthday, {lead_name}! 🎉 Wishing you a wonderful day. "
            f"If there's anything I can help you with on the real estate front, don't hesitate to reach out. "
            f"— {realtor_name}"
        )
    if trigger == "home_anniversary":
        return (
            f"Happy Home Anniversary, {lead_name}! 🏠 It's been a year (or more) since you moved in — "
            f"I hope you've been loving your home. Let me know if you ever want a market update or have any questions. "
            f"— {realtor_name}"
        )
    return (
        f"Hi {lead_name}, just checking in! Let me know if you have any real estate questions. "
        f"— {realtor_name}"
    )


def _node_finalize(state: DripCampaignState) -> dict[str, Any]:
    acs: dict = state["acs"]
    if state.get("failed"):
        acs_state.set_core_meta(acs, {"workflow_id": _WORKFLOW_ID, "status": "failed", "phase": "terminal"})
        workflow_audit.audit_run_finish(acs, status="failed")
    else:
        sent = state.get("messages_sent") or 0
        acs_state.set_core_meta(acs, {"workflow_id": _WORKFLOW_ID, "status": "completed", "phase": "done", "messages_sent": sent})
        workflow_audit.audit_log_node(acs, "finalize", extra={"messages_sent": sent})
        workflow_audit.audit_run_finish(acs, status="completed")
    return {"acs": acs}


def build_drip_campaign_graph():
    g = StateGraph(DripCampaignState)
    g.add_node("load_settings", _node_load_settings)
    g.add_node("query_eligible_leads", _node_query_eligible_leads)
    g.add_node("quarantine_filter", _node_quarantine_filter)
    g.add_node("personalize_and_send", _node_personalize_and_send)
    g.add_node("finalize", _node_finalize)

    g.set_entry_point("load_settings")
    g.add_edge("load_settings", "query_eligible_leads")
    g.add_edge("query_eligible_leads", "quarantine_filter")
    g.add_edge("quarantine_filter", "personalize_and_send")
    g.add_edge("personalize_and_send", "finalize")
    g.add_edge("finalize", END)
    return g.compile()

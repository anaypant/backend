"""lead.hot_notify_v1 — compute and store a hot-leads shortlist, notify realtor of changes.

Runs on: score update from lead.scoring_v1, or Cloud Scheduler (daily).
Read-only assist mode: no autonomous actions taken on the hot leads themselves.
"""

from __future__ import annotations

import datetime
import logging
import time
import uuid
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from clients import db_internal
from state import acs_state
from workflows import workflow_audit

_logger = logging.getLogger(__name__)

_WORKFLOW_ID = "lead.hot_notify_v1"
_DEFAULT_HOT_THRESHOLD = 70
_DEFAULT_MAX_SHORTLIST = 10


class HotLeadsState(TypedDict, total=False):
    acs: dict[str, Any]
    failed: bool
    glyde_settings: dict[str, Any]
    all_leads: list[dict[str, Any]]
    shortlist: list[dict[str, Any]]
    prev_shortlist_ids: set[str]
    new_hot_leads: list[dict[str, Any]]


def _uid(acs: dict) -> str | None:
    u = acs.get("user_id")
    return u.strip() if isinstance(u, str) and u.strip() else None


def _iso_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _node_load_settings(state: HotLeadsState) -> dict[str, Any]:
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    workflow_audit.audit_run_start(acs, _WORKFLOW_ID)

    uid = _uid(acs)
    if not uid:
        acs_state.append_error(acs, "user_id missing")
        acs_state.set_core_meta(acs, {"workflow_id": _WORKFLOW_ID, "status": "failed", "phase": "load_settings"})
        return {"acs": acs, "failed": True}

    settings_body, _ = db_internal.read_document(f"Realtors/{uid}/GlydeSettings/config", acting_uid=uid)
    workflow_audit.audit_bump_db_read(acs)
    settings = settings_body.get("data") if isinstance(settings_body.get("data"), dict) else {}

    workflow_audit.audit_log_node(acs, "load_settings", duration_ms=(time.perf_counter() - t0) * 1000)
    return {"acs": acs, "failed": False, "glyde_settings": settings}


def _node_load_scored_leads(state: HotLeadsState) -> dict[str, Any]:
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    if state.get("failed"):
        return {"acs": acs}

    uid = _uid(acs)
    if not uid:
        return {"acs": acs, "all_leads": []}

    settings = state.get("glyde_settings") or {}
    threshold = int(settings.get("hotLeadThreshold") or _DEFAULT_HOT_THRESHOLD)

    leads_body, lst = db_internal.query_collection(
        f"Realtors/{uid}/Leads",
        filters=[
            {"field": "ownerUid", "op": "==", "value": uid},
            {"field": "glydeScore", "op": ">=", "value": threshold},
        ],
        acting_uid=uid,
        limit=100,
    )
    workflow_audit.audit_bump_db_query(acs)

    leads: list[dict[str, Any]] = []
    if lst == 200 and isinstance(leads_body.get("items"), list):
        for item in leads_body["items"]:
            data = item.get("data") if isinstance(item.get("data"), dict) else {}
            if data:
                leads.append(data)

    workflow_audit.audit_log_node(acs, "load_scored_leads", duration_ms=(time.perf_counter() - t0) * 1000, extra={"count": len(leads), "threshold": threshold})
    return {"acs": acs, "all_leads": leads}


def _node_rank_shortlist(state: HotLeadsState) -> dict[str, Any]:
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    if state.get("failed"):
        return {"acs": acs}

    settings = state.get("glyde_settings") or {}
    max_count = int(settings.get("hotLeadMaxCount") or _DEFAULT_MAX_SHORTLIST)
    all_leads = state.get("all_leads") or []

    def _score_key(lead: dict) -> float:
        return float(lead.get("glydeScore") or 0)

    ranked = sorted(all_leads, key=_score_key, reverse=True)[:max_count]

    shortlist: list[dict[str, Any]] = []
    for lead in ranked:
        lead_data = lead.get("lead") if isinstance(lead.get("lead"), dict) else {}
        shortlist.append({
            "canonicalLeadId": lead.get("canonicalLeadId") or lead.get("id") or "",
            "name": lead_data.get("name") or lead_data.get("firstName") or lead.get("name") or "Unknown",
            "glydeScore": lead.get("glydeScore") or 0,
            "glydeIsHot": lead.get("glydeIsHot") or True,
            "stage": lead_data.get("stage") or lead.get("stage") or "",
            "lastContacted": lead_data.get("lastContacted") or lead.get("lastContacted") or "",
            "email": (lead_data.get("emails") or [None])[0] if isinstance(lead_data.get("emails"), list) else "",
            "phone": (lead_data.get("phones") or [None])[0] if isinstance(lead_data.get("phones"), list) else "",
            "source": lead_data.get("source") or lead.get("source") or "",
            "glydeScoreUpdatedAt": lead.get("glydeScoreUpdatedAt") or "",
        })

    workflow_audit.audit_log_node(acs, "rank_shortlist", duration_ms=(time.perf_counter() - t0) * 1000, extra={"shortlist_count": len(shortlist)})
    return {"acs": acs, "shortlist": shortlist}


def _node_diff_against_previous(state: HotLeadsState) -> dict[str, Any]:
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    if state.get("failed"):
        return {"acs": acs}

    uid = _uid(acs)
    if not uid:
        return {"acs": acs, "prev_shortlist_ids": set(), "new_hot_leads": []}

    prev_body, pst = db_internal.read_document(f"Realtors/{uid}/HotLeads/current", acting_uid=uid)
    workflow_audit.audit_bump_db_read(acs)

    prev_ids: set[str] = set()
    if pst == 200 and isinstance(prev_body.get("data"), dict):
        prev_leads = prev_body["data"].get("leads") or []
        if isinstance(prev_leads, list):
            for pl in prev_leads:
                if isinstance(pl, dict) and pl.get("canonicalLeadId"):
                    prev_ids.add(str(pl["canonicalLeadId"]))

    shortlist = state.get("shortlist") or []
    new_hot = [s for s in shortlist if s.get("canonicalLeadId") and s["canonicalLeadId"] not in prev_ids]

    workflow_audit.audit_log_node(
        acs,
        "diff_against_previous",
        duration_ms=(time.perf_counter() - t0) * 1000,
        extra={"prev_count": len(prev_ids), "new_hot": len(new_hot)},
    )
    return {"acs": acs, "prev_shortlist_ids": prev_ids, "new_hot_leads": new_hot}


def _node_store_hot_leads(state: HotLeadsState) -> dict[str, Any]:
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    if state.get("failed"):
        return {"acs": acs}

    uid = _uid(acs)
    if not uid:
        return {"acs": acs}

    shortlist = state.get("shortlist") or []
    record: dict[str, Any] = {
        "ownerUid": uid,
        "updatedAt": _iso_now(),
        "count": len(shortlist),
        "leads": shortlist,
        "workflowId": _WORKFLOW_ID,
    }
    _, st = db_internal.upsert_merge(f"Realtors/{uid}/HotLeads/current", record, acting_uid=uid)

    workflow_audit.audit_log_node(acs, "store_hot_leads", duration_ms=(time.perf_counter() - t0) * 1000, extra={"http": st, "count": len(shortlist)})
    return {"acs": acs}


def _node_notify_realtor(state: HotLeadsState) -> dict[str, Any]:
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    if state.get("failed"):
        return {"acs": acs}

    uid = _uid(acs)
    if not uid:
        return {"acs": acs}

    new_hot = state.get("new_hot_leads") or []
    if not new_hot:
        workflow_audit.audit_log_node(acs, "notify_realtor", duration_ms=(time.perf_counter() - t0) * 1000, extra={"skipped": "no_new_hot"})
        return {"acs": acs}

    count = len(new_hot)
    top = new_hot[0]
    top_name = top.get("name") or "a lead"
    top_score = top.get("glydeScore") or 0

    if count == 1:
        title = f"Hot lead: {top_name}"
        body = f"{top_name} (score {top_score}) is now on your hot list."
    else:
        title = f"{count} new hot leads"
        body = f"{top_name} (score {top_score}) and {count - 1} other(s) are now on your hot list."

    notif_id = str(uuid.uuid4())
    notif: dict[str, Any] = {
        "ownerUid": uid,
        "title": title,
        "body": body,
        "severity": "info",
        "createdAt": _iso_now(),
        "source": _WORKFLOW_ID,
        "hotLeadCount": count,
    }
    _, st = db_internal.upsert_merge(f"Realtors/{uid}/Notifications/{notif_id}", notif, acting_uid=uid)

    workflow_audit.audit_log_node(acs, "notify_realtor", duration_ms=(time.perf_counter() - t0) * 1000, extra={"http": st, "new_hot": count})
    return {"acs": acs}


def _node_finalize(state: HotLeadsState) -> dict[str, Any]:
    acs: dict = state["acs"]
    if state.get("failed"):
        acs_state.set_core_meta(acs, {"workflow_id": _WORKFLOW_ID, "status": "failed", "phase": "terminal"})
        workflow_audit.audit_run_finish(acs, status="failed")
    else:
        shortlist = state.get("shortlist") or []
        new_hot = state.get("new_hot_leads") or []
        acs_state.set_core_meta(acs, {
            "workflow_id": _WORKFLOW_ID,
            "status": "completed",
            "phase": "done",
            "shortlist_count": len(shortlist),
            "new_hot_count": len(new_hot),
        })
        workflow_audit.audit_log_node(acs, "finalize")
        workflow_audit.audit_run_finish(acs, status="completed")
    return {"acs": acs}


def build_hot_leads_graph():
    g = StateGraph(HotLeadsState)
    g.add_node("load_settings", _node_load_settings)
    g.add_node("load_scored_leads", _node_load_scored_leads)
    g.add_node("rank_shortlist", _node_rank_shortlist)
    g.add_node("diff_against_previous", _node_diff_against_previous)
    g.add_node("store_hot_leads", _node_store_hot_leads)
    g.add_node("notify_realtor", _node_notify_realtor)
    g.add_node("finalize", _node_finalize)

    g.set_entry_point("load_settings")
    g.add_edge("load_settings", "load_scored_leads")
    g.add_edge("load_scored_leads", "rank_shortlist")
    g.add_edge("rank_shortlist", "diff_against_previous")
    g.add_edge("diff_against_previous", "store_hot_leads")
    g.add_edge("store_hot_leads", "notify_realtor")
    g.add_edge("notify_realtor", "finalize")
    g.add_edge("finalize", END)
    return g.compile()

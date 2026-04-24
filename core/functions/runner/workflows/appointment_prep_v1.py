"""appointment.prep_v1 — generate a prep document for an upcoming FUB appointment."""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from clients import db_internal, llm_internal
from state import acs_state
from workflows import workflow_audit

_logger = logging.getLogger(__name__)

_WORKFLOW_ID = "appointment.prep_v1"


class AppointmentPrepState(TypedDict, total=False):
    acs: dict[str, Any]
    failed: bool
    realtor_profile: dict[str, Any]
    appointment: dict[str, Any]
    contact_context: dict[str, Any]
    prep_doc: str


def _uid(acs: dict) -> str | None:
    u = acs.get("user_id")
    return u.strip() if isinstance(u, str) and u.strip() else None


def _node_load_realtor_profile(state: AppointmentPrepState) -> dict[str, Any]:
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    workflow_audit.audit_run_start(acs, _WORKFLOW_ID)

    uid = _uid(acs)
    if not uid:
        acs_state.append_error(acs, "user_id missing; cannot load realtor profile")
        acs_state.set_core_meta(acs, {"workflow_id": _WORKFLOW_ID, "status": "failed", "phase": "load_realtor"})
        workflow_audit.audit_log_node(acs, "load_realtor_profile", duration_ms=(time.perf_counter() - t0) * 1000, extra={"error": "no_uid"})
        return {"acs": acs, "failed": True}

    body, st = db_internal.read_document(f"Realtors/{uid}", acting_uid=uid)
    workflow_audit.audit_bump_db_read(acs)
    profile = body.get("data") if isinstance(body.get("data"), dict) else {}
    if st >= 400 and st != 404:
        acs_state.append_error(acs, f"realtor profile read failed: {st}")
        acs_state.set_core_meta(acs, {"workflow_id": _WORKFLOW_ID, "status": "failed", "phase": "load_realtor"})
        workflow_audit.audit_log_node(acs, "load_realtor_profile", duration_ms=(time.perf_counter() - t0) * 1000, extra={"http": st})
        return {"acs": acs, "failed": True}

    workflow_audit.audit_log_node(acs, "load_realtor_profile", duration_ms=(time.perf_counter() - t0) * 1000, extra={"http": st})
    return {"acs": acs, "failed": False, "realtor_profile": profile}


def _node_load_appointment(state: AppointmentPrepState) -> dict[str, Any]:
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    if state.get("failed"):
        return {"acs": acs}

    payload = acs.get("payload") if isinstance(acs.get("payload"), dict) else {}
    appt = payload.get("appointment") if isinstance(payload.get("appointment"), dict) else {}
    if not appt:
        appt = {
            "id": payload.get("id") or payload.get("appointmentId"),
            "title": payload.get("title") or payload.get("appointmentTitle") or "Appointment",
            "description": payload.get("description") or "",
            "start": payload.get("start") or payload.get("startDate") or payload.get("appointmentDate"),
            "end": payload.get("end") or payload.get("endDate"),
            "address": payload.get("address") or "",
            "status": payload.get("status") or "scheduled",
        }

    workflow_audit.audit_log_node(acs, "load_appointment", duration_ms=(time.perf_counter() - t0) * 1000, extra={"has_appt": bool(appt.get("id"))})
    return {"acs": acs, "appointment": appt}


def _node_fetch_contact_context(state: AppointmentPrepState) -> dict[str, Any]:
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    if state.get("failed"):
        return {"acs": acs}

    uid = _uid(acs)
    if not uid:
        return {"acs": acs, "contact_context": {}}

    payload = acs.get("payload") if isinstance(acs.get("payload"), dict) else {}
    person = payload.get("person") if isinstance(payload.get("person"), dict) else {}
    person_id = person.get("id") or payload.get("personId")

    contact: dict[str, Any] = dict(person)

    if person_id:
        fub_data = payload.get("_fub") if isinstance(payload.get("_fub"), dict) else {}
        if fub_data:
            contact.update(fub_data)
        canonical_lead_id = f"fub_{person_id}"
        lead_path = f"Realtors/{uid}/Leads/{canonical_lead_id}"
        lead_body, lead_st = db_internal.read_document(lead_path, acting_uid=uid)
        workflow_audit.audit_bump_db_read(acs)
        if lead_st == 200 and isinstance(lead_body.get("data"), dict):
            contact["_acs_lead"] = lead_body["data"]

    workflow_audit.audit_log_node(
        acs,
        "fetch_contact_context",
        duration_ms=(time.perf_counter() - t0) * 1000,
        extra={"person_id": person_id, "contact_keys": list(contact.keys())[:15]},
    )
    return {"acs": acs, "contact_context": contact}


def _node_llm_generate_prep_doc(state: AppointmentPrepState) -> dict[str, Any]:
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    if state.get("failed"):
        return {"acs": acs}

    appt = state.get("appointment") or {}
    contact = state.get("contact_context") or {}
    realtor = state.get("realtor_profile") or {}

    system_prompt = (
        "You are an assistant preparing a real estate agent for an upcoming appointment. "
        "Generate a structured preparation document including: client background, property context, "
        "key talking points, potential objections and responses, and recommended next steps. "
        "Be concise, professional, and actionable. Output plain text, not JSON."
    )
    user_content = json.dumps(
        {
            "appointment": appt,
            "contact": contact,
            "realtor_name": realtor.get("displayName") or realtor.get("email") or "the agent",
            "instruction": (
                "Write an appointment preparation document for the agent. "
                "Include: 1) Client summary 2) Property/meeting context 3) Key talking points "
                "4) Potential concerns to address 5) Suggested next steps after the meeting."
            ),
        },
        default=str,
    )[:80_000]

    try:
        body, st = llm_internal.complete(
            model=(os.environ.get("ACS_PREP_LLM_MODEL") or "openai/gpt-4o-mini").strip(),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            response_format="text",
        )
    except Exception as e:
        acs_state.append_error(acs, f"prep doc llm error: {e!s}")
        acs_state.set_core_meta(acs, {"workflow_id": _WORKFLOW_ID, "status": "failed", "phase": "llm_generate"})
        return {"acs": acs, "failed": True}

    workflow_audit.audit_bump_llm(acs)
    if st >= 400:
        acs_state.append_error(acs, f"prep doc llm http {st}")
        acs_state.set_core_meta(acs, {"workflow_id": _WORKFLOW_ID, "status": "failed", "phase": "llm_generate"})
        return {"acs": acs, "failed": True}

    doc_text = (body.get("text") or "").strip()
    if not doc_text:
        doc_text = (
            f"Appointment: {appt.get('title', 'N/A')}\n"
            f"Date: {appt.get('start', 'N/A')}\n"
            f"Client: {contact.get('name') or contact.get('firstName') or 'Unknown'}\n"
            "No detailed prep document could be generated for this appointment."
        )

    workflow_audit.audit_log_node(acs, "llm_generate_prep_doc", duration_ms=(time.perf_counter() - t0) * 1000, extra={"doc_len": len(doc_text)})
    return {"acs": acs, "prep_doc": doc_text}


def _node_store_prep_doc(state: AppointmentPrepState) -> dict[str, Any]:
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    if state.get("failed"):
        return {"acs": acs}

    uid = _uid(acs)
    if not uid:
        return {"acs": acs}

    appt = state.get("appointment") or {}
    prep_doc = state.get("prep_doc") or ""
    appt_id = str(appt.get("id") or uuid.uuid4())
    doc_path = f"Realtors/{uid}/AppointmentPreps/{appt_id}"

    record: dict[str, Any] = {
        "ownerUid": uid,
        "appointmentId": appt_id,
        "appointmentTitle": appt.get("title") or "Appointment",
        "appointmentStart": appt.get("start"),
        "prepDoc": prep_doc,
        "createdAt": _iso_now(),
        "workflowId": _WORKFLOW_ID,
    }
    _, st = db_internal.upsert_merge(doc_path, record, acting_uid=uid)
    workflow_audit.audit_bump_db_read(acs)

    meta = acs_state.ensure_metadata(acs)
    meta.setdefault("appointmentPrep", {})
    if isinstance(meta["appointmentPrep"], dict):
        meta["appointmentPrep"]["stored"] = st < 400
        meta["appointmentPrep"]["path"] = doc_path

    workflow_audit.audit_log_node(acs, "store_prep_doc", duration_ms=(time.perf_counter() - t0) * 1000, extra={"http": st, "path": doc_path})
    return {"acs": acs}


def _node_create_notification(state: AppointmentPrepState) -> dict[str, Any]:
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    if state.get("failed"):
        return {"acs": acs}

    uid = _uid(acs)
    if not uid:
        return {"acs": acs}

    appt = state.get("appointment") or {}
    notif_id = str(uuid.uuid4())
    notif_path = f"Realtors/{uid}/Notifications/{notif_id}"
    title = appt.get("title") or "Upcoming Appointment"
    start = appt.get("start") or ""
    body_text = f"Prep document ready for: {title}"
    if start:
        body_text += f" on {start}"

    notif: dict[str, Any] = {
        "ownerUid": uid,
        "title": "Appointment prep ready",
        "body": body_text,
        "severity": "info",
        "createdAt": _iso_now(),
        "source": _WORKFLOW_ID,
        "appointmentId": str(appt.get("id") or ""),
    }
    _, st = db_internal.upsert_merge(notif_path, notif, acting_uid=uid)

    workflow_audit.audit_log_node(acs, "create_notification", duration_ms=(time.perf_counter() - t0) * 1000, extra={"http": st})
    return {"acs": acs}


def _node_finalize(state: AppointmentPrepState) -> dict[str, Any]:
    acs: dict = state["acs"]
    if state.get("failed"):
        acs_state.set_core_meta(acs, {"workflow_id": _WORKFLOW_ID, "status": "failed", "phase": "terminal"})
        workflow_audit.audit_run_finish(acs, status="failed", detail="prior_failure")
    else:
        acs_state.set_core_meta(acs, {"workflow_id": _WORKFLOW_ID, "status": "completed", "phase": "done"})
        workflow_audit.audit_log_node(acs, "finalize")
        workflow_audit.audit_run_finish(acs, status="completed")
    return {"acs": acs}


def _iso_now() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def build_appointment_prep_graph():
    g = StateGraph(AppointmentPrepState)
    g.add_node("load_realtor_profile", _node_load_realtor_profile)
    g.add_node("load_appointment", _node_load_appointment)
    g.add_node("fetch_contact_context", _node_fetch_contact_context)
    g.add_node("llm_generate_prep_doc", _node_llm_generate_prep_doc)
    g.add_node("store_prep_doc", _node_store_prep_doc)
    g.add_node("create_notification", _node_create_notification)
    g.add_node("finalize", _node_finalize)

    g.set_entry_point("load_realtor_profile")
    g.add_edge("load_realtor_profile", "load_appointment")
    g.add_edge("load_appointment", "fetch_contact_context")
    g.add_edge("fetch_contact_context", "llm_generate_prep_doc")
    g.add_edge("llm_generate_prep_doc", "store_prep_doc")
    g.add_edge("store_prep_doc", "create_notification")
    g.add_edge("create_notification", "finalize")
    g.add_edge("finalize", END)
    return g.compile()

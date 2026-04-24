"""communication.auto_reply_v1 — draft and optionally send an auto-reply to an inbound FUB message.

volatile_external: True — by default runs in analytical (draft-only) mode.
The realtor must set GlydeSettings.autoReplyEnabled=True AND the execution policy must
allow volatile_external for an actual reply to be sent.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import time
import uuid
from typing import Any, Literal, TypedDict

from langgraph.graph import END, StateGraph

from clients import db_internal, llm_internal
from state import acs_state
from state.execution_policy import volatile_external_allowed
from workflows import workflow_audit

_logger = logging.getLogger(__name__)

_WORKFLOW_ID = "communication.auto_reply_v1"
_MAX_THREAD_NOTES = 10


class AutoReplyState(TypedDict, total=False):
    acs: dict[str, Any]
    failed: bool
    settings_enabled: bool
    realtor_profile: dict[str, Any]
    glyde_settings: dict[str, Any]
    thread_context: list[dict[str, Any]]
    draft_reply: str
    sent: bool


def _uid(acs: dict) -> str | None:
    u = acs.get("user_id")
    return u.strip() if isinstance(u, str) and u.strip() else None


def _iso_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _node_load_settings(state: AutoReplyState) -> dict[str, Any]:
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


def _node_check_enabled(state: AutoReplyState) -> dict[str, Any]:
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    if state.get("failed"):
        return {"acs": acs}

    settings = state.get("glyde_settings") or {}
    enabled_workflows = settings.get("enabledWorkflows") or []
    auto_reply_on = bool(settings.get("autoReplyEnabled"))
    workflow_enabled = _WORKFLOW_ID in enabled_workflows or "communication.auto_reply_v1" in enabled_workflows

    enabled = auto_reply_on and workflow_enabled
    workflow_audit.audit_log_node(acs, "check_enabled", duration_ms=(time.perf_counter() - t0) * 1000, extra={"enabled": enabled})
    return {"acs": acs, "settings_enabled": enabled}


def _node_fetch_thread_context(state: AutoReplyState) -> dict[str, Any]:
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    if state.get("failed"):
        return {"acs": acs}

    payload = acs.get("payload") if isinstance(acs.get("payload"), dict) else {}

    thread: list[dict[str, Any]] = []

    current_msg: dict[str, Any] = {
        "role": "client",
        "content": payload.get("body") or payload.get("message") or payload.get("text") or payload.get("emailBody") or "",
        "subject": payload.get("subject") or payload.get("emailSubject") or "",
        "type": payload.get("messageType") or payload.get("type") or "unknown",
        "timestamp": payload.get("createdAt") or payload.get("sentAt") or _iso_now(),
    }
    if current_msg["content"]:
        thread.append(current_msg)

    notes = payload.get("notes") if isinstance(payload.get("notes"), list) else []
    for note in notes[:_MAX_THREAD_NOTES]:
        if isinstance(note, dict):
            thread.append({
                "role": "agent" if note.get("isOutbound") else "client",
                "content": note.get("body") or note.get("content") or "",
                "timestamp": note.get("createdAt") or "",
            })

    workflow_audit.audit_log_node(acs, "fetch_thread_context", duration_ms=(time.perf_counter() - t0) * 1000, extra={"thread_len": len(thread)})
    return {"acs": acs, "thread_context": thread}


def _node_llm_draft_reply(state: AutoReplyState) -> dict[str, Any]:
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    if state.get("failed"):
        return {"acs": acs}

    realtor = state.get("realtor_profile") or {}
    settings = state.get("glyde_settings") or {}
    thread = state.get("thread_context") or []

    custom_prompt = realtor.get("aiPreferences", {}).get("customSystemPrompt") or ""
    tone_instruction = settings.get("autoReplyTone") or "professional and warm"
    realtor_name = realtor.get("displayName") or realtor.get("email") or "the agent"

    system_msg = (
        f"You are a real estate assistant replying on behalf of {realtor_name}. "
        f"Write a reply that is {tone_instruction}. Be concise (2-4 sentences). "
        "Do not make up property details or commitments. "
        + (f"Additional instructions: {custom_prompt}" if custom_prompt else "")
    )

    user_content = json.dumps(
        {
            "thread": thread,
            "instruction": (
                "Draft a reply to the most recent client message in this thread. "
                "Return JSON only: {\"reply\": <string>, \"subject\": <string or null>}"
            ),
        },
        default=str,
    )[:40_000]

    draft = ""
    try:
        body, st = llm_internal.complete(
            model=(os.environ.get("ACS_AUTO_REPLY_LLM_MODEL") or "openai/gpt-4o-mini").strip(),
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_content},
            ],
            response_format="json",
        )
        workflow_audit.audit_bump_llm(acs)
        if st < 400:
            raw = body.get("text") or body.get("json") or ""
            try:
                parsed = json.loads(raw) if isinstance(raw, str) else (raw if isinstance(raw, dict) else {})
                draft = str(parsed.get("reply") or "").strip()
            except (json.JSONDecodeError, TypeError):
                draft = str(raw).strip()[:2000]
    except Exception as e:
        acs_state.append_error(acs, f"auto reply llm error: {e!s}")
        acs_state.set_core_meta(acs, {"workflow_id": _WORKFLOW_ID, "status": "failed", "phase": "llm_draft"})
        return {"acs": acs, "failed": True}

    if not draft:
        draft = "Thank you for reaching out! I'll be in touch shortly."

    meta = acs_state.ensure_metadata(acs)
    meta.setdefault("autoReply", {})
    if isinstance(meta["autoReply"], dict):
        meta["autoReply"]["draft_len"] = len(draft)

    workflow_audit.audit_log_node(acs, "llm_draft_reply", duration_ms=(time.perf_counter() - t0) * 1000, extra={"draft_len": len(draft)})
    return {"acs": acs, "draft_reply": draft}


def _node_send_reply(state: AutoReplyState) -> dict[str, Any]:
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    if state.get("failed"):
        return {"acs": acs, "sent": False}

    draft = state.get("draft_reply") or ""
    settings_enabled = bool(state.get("settings_enabled"))

    if not settings_enabled:
        workflow_audit.audit_log_node(acs, "send_reply", duration_ms=(time.perf_counter() - t0) * 1000, extra={"skipped": "auto_reply_disabled_in_settings"})
        return {"acs": acs, "sent": False}

    if not volatile_external_allowed(acs):
        meta = acs_state.ensure_metadata(acs)
        meta.setdefault("autoReply", {})
        if isinstance(meta["autoReply"], dict):
            meta["autoReply"]["mode"] = "analytical_draft_only"
        workflow_audit.audit_log_node(acs, "send_reply", duration_ms=(time.perf_counter() - t0) * 1000, extra={"skipped": "volatile_external_not_allowed"})
        return {"acs": acs, "sent": False}

    payload = acs.get("payload") if isinstance(acs.get("payload"), dict) else {}
    person_id = payload.get("personId") or (payload.get("person") or {}).get("id")
    msg_type = payload.get("messageType") or payload.get("type") or "note"

    meta = acs_state.ensure_metadata(acs)
    action: dict[str, Any] = {
        "name": "sendMessage" if msg_type in ("text", "sms") else "createNote",
        "payload": {
            "personId": person_id,
            "body": draft,
            "isOutbound": True,
        },
        "effect": "volatile_external",
    }
    actions = [action]
    meta["outboundActions"] = actions

    meta.setdefault("autoReply", {})
    if isinstance(meta["autoReply"], dict):
        meta["autoReply"]["action"] = action["name"]
        meta["autoReply"]["mode"] = "live_send"

    workflow_audit.audit_log_node(acs, "send_reply", duration_ms=(time.perf_counter() - t0) * 1000, extra={"action": action["name"]})
    return {"acs": acs, "sent": True}


def _node_log_communication(state: AutoReplyState) -> dict[str, Any]:
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    if state.get("failed"):
        return {"acs": acs}

    uid = _uid(acs)
    if not uid:
        return {"acs": acs}

    payload = acs.get("payload") if isinstance(acs.get("payload"), dict) else {}
    log_id = str(uuid.uuid4())
    log_record: dict[str, Any] = {
        "ownerUid": uid,
        "personId": payload.get("personId") or (payload.get("person") or {}).get("id"),
        "direction": "inbound",
        "messageType": payload.get("messageType") or payload.get("type") or "unknown",
        "draft": state.get("draft_reply") or "",
        "sent": bool(state.get("sent")),
        "settingsEnabled": bool(state.get("settings_enabled")),
        "createdAt": _iso_now(),
        "workflowId": _WORKFLOW_ID,
    }
    _, st = db_internal.upsert_merge(f"Realtors/{uid}/CommunicationLog/{log_id}", log_record, acting_uid=uid)

    workflow_audit.audit_log_node(acs, "log_communication", duration_ms=(time.perf_counter() - t0) * 1000, extra={"http": st})
    return {"acs": acs}


def _node_finalize(state: AutoReplyState) -> dict[str, Any]:
    acs: dict = state["acs"]
    if state.get("failed"):
        acs_state.set_core_meta(acs, {"workflow_id": _WORKFLOW_ID, "status": "failed", "phase": "terminal"})
        workflow_audit.audit_run_finish(acs, status="failed")
    else:
        acs_state.set_core_meta(acs, {"workflow_id": _WORKFLOW_ID, "status": "completed", "phase": "done"})
        workflow_audit.audit_log_node(acs, "finalize")
        workflow_audit.audit_run_finish(acs, status="completed")
    return {"acs": acs}


def build_auto_reply_graph():
    g = StateGraph(AutoReplyState)
    g.add_node("load_settings", _node_load_settings)
    g.add_node("check_enabled", _node_check_enabled)
    g.add_node("fetch_thread_context", _node_fetch_thread_context)
    g.add_node("llm_draft_reply", _node_llm_draft_reply)
    g.add_node("send_reply", _node_send_reply)
    g.add_node("log_communication", _node_log_communication)
    g.add_node("finalize", _node_finalize)

    g.set_entry_point("load_settings")
    g.add_edge("load_settings", "check_enabled")
    g.add_edge("check_enabled", "fetch_thread_context")
    g.add_edge("fetch_thread_context", "llm_draft_reply")
    g.add_edge("llm_draft_reply", "send_reply")
    g.add_edge("send_reply", "log_communication")
    g.add_edge("log_communication", "finalize")
    g.add_edge("finalize", END)
    return g.compile()

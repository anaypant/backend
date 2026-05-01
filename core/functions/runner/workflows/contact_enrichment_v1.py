"""contact.enrichment_v1 — load profile/contact, normalize, research, synthesize, policy, map, optional egress."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Literal, TypedDict

from langgraph.graph import END, StateGraph

from clients import db_internal, llm_internal
from clients import web_research_internal
from state import acs_state
from state.execution_policy import volatile_external_allowed
from tools import registry as tool_registry
from workflows import normalize_integration_payload, workflow_audit

_logger = logging.getLogger(__name__)

_WORKFLOW_ID = "contact.enrichment_v1"


class EnrichmentState(TypedDict, total=False):
    acs: dict[str, Any]
    failed: bool
    halt_duplicate: bool
    realtor_profile: dict[str, Any]
    raw_contact: dict[str, Any]
    normalized_contact: dict[str, Any]
    research: dict[str, Any]
    synthesis_updates: dict[str, Any]
    screened_updates: dict[str, Any]


def _uid(acs: dict) -> str | None:
    u = acs.get("user_id")
    return u.strip() if isinstance(u, str) and u.strip() else None


def _node_load_realtor_profile(state: EnrichmentState) -> dict[str, Any]:
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
    if st == 404:
        profile = {}
    elif st >= 400:
        acs_state.append_error(acs, f"realtor profile read failed: {st}")
        acs_state.set_core_meta(acs, {"workflow_id": _WORKFLOW_ID, "status": "failed", "phase": "load_realtor"})
        workflow_audit.audit_log_node(acs, "load_realtor_profile", duration_ms=(time.perf_counter() - t0) * 1000, extra={"http": st})
        return {"acs": acs, "failed": True}

    meta = acs_state.ensure_metadata(acs)
    meta.setdefault("contactEnrichment", {})
    if isinstance(meta["contactEnrichment"], dict):
        meta["contactEnrichment"]["realtorProfileLoaded"] = True

    workflow_audit.audit_log_node(acs, "load_realtor_profile", duration_ms=(time.perf_counter() - t0) * 1000, extra={"http": st})
    return {"acs": acs, "failed": False, "realtor_profile": profile}


def _node_load_contact(state: EnrichmentState) -> dict[str, Any]:
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    if state.get("failed"):
        return {"acs": acs}
    payload = acs.get("payload") if isinstance(acs.get("payload"), dict) else {}
    workflow_audit.audit_log_node(acs, "load_contact", duration_ms=(time.perf_counter() - t0) * 1000, extra={"keys": list(payload.keys())[:20]})
    return {"acs": acs, "raw_contact": dict(payload)}


def _node_check_internal_client(state: EnrichmentState) -> dict[str, Any]:
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    if state.get("failed"):
        return {"acs": acs}
    uid = _uid(acs)
    if not uid:
        return {"acs": acs, "failed": True}

    norm = normalize_integration_payload.normalize_contact(acs)
    doc_id = normalize_integration_payload.internal_client_doc_id(norm)
    path = f"Realtors/{uid}/InternalClients/{doc_id}"
    body, st = db_internal.read_document(path, acting_uid=uid)
    workflow_audit.audit_bump_db_read(acs)

    if st not in (200, 404):
        acs_state.append_error(acs, f"internal client index read failed: {st}")
        acs_state.set_core_meta(acs, {"workflow_id": _WORKFLOW_ID, "status": "failed", "phase": "check_internal_client"})
        workflow_audit.audit_log_node(acs, "check_internal_client", duration_ms=(time.perf_counter() - t0) * 1000, extra={"http": st})
        return {"acs": acs, "failed": True, "normalized_contact": norm}

    halt = st == 200 and isinstance(body.get("data"), dict)
    meta = acs_state.ensure_metadata(acs)
    ce = meta.setdefault("contactEnrichment", {})
    if isinstance(ce, dict):
        ce["internalClientPath"] = path
        ce["internalClientExists"] = halt

    workflow_audit.audit_log_node(
        acs,
        "check_internal_client",
        duration_ms=(time.perf_counter() - t0) * 1000,
        extra={"path": path, "http": st, "exists": halt},
    )
    return {"acs": acs, "halt_duplicate": halt, "normalized_contact": norm}


def _node_normalize(state: EnrichmentState) -> dict[str, Any]:
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    if state.get("failed") or state.get("halt_duplicate"):
        return {"acs": acs}
    norm = state.get("normalized_contact") or normalize_integration_payload.normalize_contact(acs)
    meta = acs_state.ensure_metadata(acs)
    meta.setdefault("contactEnrichment", {})
    if isinstance(meta["contactEnrichment"], dict):
        meta["contactEnrichment"]["normalized"] = norm

    workflow_audit.audit_log_node(acs, "normalize", duration_ms=(time.perf_counter() - t0) * 1000)
    return {"acs": acs, "normalized_contact": norm}


def _node_web_research(state: EnrichmentState) -> dict[str, Any]:
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    if state.get("failed") or state.get("halt_duplicate"):
        return {"acs": acs}

    norm = state.get("normalized_contact") or {}
    display_name = (norm.get("display_name") or "").strip()
    emails = norm.get("emails") if isinstance(norm.get("emails"), list) else []

    # Only include email in the search query when it looks like a real personal/business
    # address — skip test/placeholder domains that would confuse the search engine.
    _SKIP_EMAIL_DOMAINS = {"example.com", "example.org", "example.net", "test.com",
                           "localhost", "acs-test.dev", "mailinator.com", "yopmail.com"}
    real_email = ""
    for _e in emails:
        if not isinstance(_e, str) or not _e.strip():
            continue
        _domain = _e.rsplit("@", 1)[-1].lower().strip() if "@" in _e else ""
        if _domain and _domain not in _SKIP_EMAIL_DOMAINS:
            real_email = _e.strip()
            break

    if display_name:
        # Build a focused query using the person's name as the primary signal.
        # Real email helps disambiguate common names; adding "real estate" surfaces CRM context.
        q_parts = [display_name]
        if real_email:
            q_parts.append(real_email)
        q_parts.append("real estate")
    else:
        # Fallback for contacts with no name yet (use provider+id for debugging).
        q_parts = [
            f"Contact from {norm.get('provider')}",
            f"id={norm.get('external_person_id')}",
        ]
    query = " ".join(str(p) for p in q_parts if p).strip()

    wr_limit: int | None = None
    raw_lim = (os.environ.get("ACS_WEB_RESEARCH_RESULT_LIMIT") or "").strip()
    if raw_lim:
        try:
            wr_limit = int(raw_lim)
        except ValueError:
            wr_limit = None

    res, st = web_research_internal.research_query_to_summary(query, result_limit=wr_limit)
    for _ in range(max(1, int(res.get("llm_calls") or 1))):
        workflow_audit.audit_bump_llm(acs)
    meta = acs_state.ensure_metadata(acs)
    ce = meta.setdefault("contactEnrichment", {})
    if isinstance(ce, dict):
        ce["webResearch"] = {
            "http_status": st,
            "mode": res.get("mode"),
            "query": query,
            "sources_count": len(res.get("sources") or []),
            "pipeline": res.get("pipeline"),
        }

    if st >= 400:
        acs_state.append_error(acs, f"web_research failed: {st}")
        acs_state.set_core_meta(acs, {"workflow_id": _WORKFLOW_ID, "status": "failed", "phase": "web_research"})
        workflow_audit.audit_log_node(acs, "web_research", duration_ms=(time.perf_counter() - t0) * 1000, extra={"http": st})
        return {"acs": acs, "failed": True, "research": res}

    workflow_audit.audit_log_node(
        acs,
        "web_research",
        duration_ms=(time.perf_counter() - t0) * 1000,
        extra={"http": st, "sources": len(res.get("sources") or [])},
    )
    return {"acs": acs, "research": res}


def _coerce_synthesis_updates(parsed: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """
    Models sometimes return ``suggested_note`` / ``tags`` at the top level instead of under ``updates``.
    Returns ``(updates_dict, coercion_label)`` for audit.
    """
    if not isinstance(parsed, dict):
        return {}, "not_dict"
    out: dict[str, Any] = {}
    inner = parsed.get("updates")
    if isinstance(inner, dict):
        for k in ("suggested_note", "tags", "custom_fields"):
            if k in inner:
                out[k] = inner[k]
    if isinstance(parsed.get("suggested_note"), str) and str(parsed["suggested_note"]).strip():
        if not (isinstance(out.get("suggested_note"), str) and out["suggested_note"].strip()):
            out["suggested_note"] = parsed["suggested_note"]
    if isinstance(parsed.get("tags"), list) and not out.get("tags"):
        out["tags"] = parsed["tags"]
    if isinstance(parsed.get("custom_fields"), dict) and not out.get("custom_fields"):
        out["custom_fields"] = parsed["custom_fields"]
    if not out:
        return {}, "empty"
    if isinstance(inner, dict) and any(k in inner for k in ("suggested_note", "tags", "custom_fields")):
        return out, "nested_updates"
    return out, "top_level_fields"


def _fallback_suggested_note_fub(norm: dict[str, Any], research: dict[str, Any]) -> str:
    """Deterministic note when the enrichment LLM returns no text but we have a CRM person."""
    pid = norm.get("person_id")
    name = (norm.get("display_name") or "").strip()
    if not name and isinstance(pid, int):
        name = f"FUB person {pid}"
    if not name:
        name = "FUB contact"
    emails = norm.get("emails") if isinstance(norm.get("emails"), list) else []
    first_email = emails[0].strip() if emails and isinstance(emails[0], str) else ""
    email_seg = f" On file: {first_email}." if first_email else ""
    summ = (research.get("summary") or "").strip()
    if summ:
        return f"ACS enrichment — {name}.{email_seg} Web summary: {summ[:2000]}".strip()
    return (
        f"ACS enrichment — {name}.{email_seg} "
        "No web research sources were returned this run; CRM fields above are from Follow Up Boss."
    ).strip()


def _node_synthesis(state: EnrichmentState) -> dict[str, Any]:
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    if state.get("failed") or state.get("halt_duplicate"):
        return {"acs": acs}

    norm = state.get("normalized_contact") or {}
    research = state.get("research") or {}
    must_note = (
        norm.get("provider") == "followupboss"
        and isinstance(norm.get("person_id"), int)
        and norm["person_id"] > 0
    )
    note_rule = (
        "When normalized_contact.provider is followupboss and normalized_contact.person_id is a positive integer, "
        "the object updates MUST include suggested_note as a non-empty string (at least one full sentence). "
        "Combine display_name, emails, phones from normalized_contact with research_summary. "
        "If research_summary is empty or research_sources is empty, still write a short CRM-only summary "
        "from normalized_contact — do not return an empty updates object."
        if must_note
        else ""
    )
    schema = (
        "Return JSON only with keys: "
        "updates (object with optional keys: suggested_note string, tags array of strings, "
        "custom_fields object of string->string), confidence (string), rationale (string). "
        "Do not include SSN, credit card numbers, or passwords. Keep suggested_note under 4000 characters. "
        f"{note_rule}"
    )
    messages = [
        {
            "role": "user",
            "content": json.dumps(
                {
                    "normalized_contact": norm,
                    "research_summary": research.get("summary"),
                    "research_sources": research.get("sources"),
                    "instruction": schema,
                },
                default=str,
            )[:120_000],
        }
    ]
    try:
        body, st = llm_internal.complete(
            model=(os.environ.get("ACS_ENRICHMENT_LLM_MODEL") or "openai/gpt-4o-mini").strip(),
            messages=messages,
            provider=(os.environ.get("ACS_ENRICHMENT_LLM_PROVIDER") or "openrouter").strip() or "openrouter",
            response_format="json",
        )
    except Exception as e:
        acs_state.append_error(acs, f"synthesis llm error: {e!s}")
        acs_state.set_core_meta(acs, {"workflow_id": _WORKFLOW_ID, "status": "failed", "phase": "synthesis"})
        return {"acs": acs, "failed": True}

    workflow_audit.audit_bump_llm(acs)
    if st >= 400:
        acs_state.append_error(acs, f"synthesis llm http {st}")
        acs_state.set_core_meta(acs, {"workflow_id": _WORKFLOW_ID, "status": "failed", "phase": "synthesis"})
        return {"acs": acs, "failed": True}

    raw = body.get("text") if isinstance(body.get("text"), str) else ""
    updates: dict[str, Any] = {}
    coercion = "empty_body"
    try:
        parsed = json.loads(raw) if raw.strip() else {}
        if isinstance(parsed, dict):
            updates, coercion = _coerce_synthesis_updates(parsed)
        else:
            updates, coercion = {}, "not_object_json"
    except json.JSONDecodeError:
        updates = {}
        coercion = "json_decode_error"

    sn0 = updates.get("suggested_note")
    used_fallback = False
    if must_note and (not isinstance(sn0, str) or not sn0.strip()):
        updates["suggested_note"] = _fallback_suggested_note_fub(norm, research)
        used_fallback = True

    meta = acs_state.ensure_metadata(acs)
    ce = meta.setdefault("contactEnrichment", {})
    if isinstance(ce, dict):
        ce["synthesis"] = {
            "http_status": st,
            "keys": list(updates.keys()),
            "coercion": coercion,
            "fallback_note": used_fallback,
        }

    sn = updates.get("suggested_note")
    sn_len = len(sn.strip()) if isinstance(sn, str) else 0
    tags = updates.get("tags")
    tag_n = len(tags) if isinstance(tags, list) else 0
    workflow_audit.audit_log_node(
        acs,
        "synthesis",
        duration_ms=(time.perf_counter() - t0) * 1000,
        extra={
            "update_keys": list(updates.keys()),
            "suggested_note_len": sn_len,
            "tags_len": tag_n,
            "coercion": coercion,
            "fallback_note": used_fallback,
        },
    )
    return {"acs": acs, "synthesis_updates": updates}


_PII_PATTERNS = (
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[redacted-ssn]"),
    (re.compile(r"\b\d{3}\s*\d{3}\s*\d{4}\s*\d{4}\b"), "[redacted-pan]"),
)


def _redact_string(s: str) -> str:
    out = s
    for rx, repl in _PII_PATTERNS:
        out = rx.sub(repl, out)
    return out


def _node_policy_screen(state: EnrichmentState) -> dict[str, Any]:
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    if state.get("failed") or state.get("halt_duplicate"):
        return {"acs": acs}

    raw_updates = state.get("synthesis_updates") or {}
    allowed_top = {"suggested_note", "tags", "custom_fields"}
    screened: dict[str, Any] = {}
    for k, v in raw_updates.items():
        if k not in allowed_top:
            continue
        if k == "suggested_note" and isinstance(v, str):
            note = _redact_string(v)[:8000]
            screened[k] = note
        elif k == "tags" and isinstance(v, list):
            screened[k] = [str(x)[:120] for x in v[:25] if isinstance(x, (str, int, float))]
        elif k == "custom_fields" and isinstance(v, dict):
            cf: dict[str, str] = {}
            for ck, cv in list(v.items())[:40]:
                if isinstance(ck, str) and isinstance(cv, (str, int, float)):
                    cf[ck[:80]] = _redact_string(str(cv))[:2000]
            screened[k] = cf

    meta = acs_state.ensure_metadata(acs)
    ce = meta.setdefault("contactEnrichment", {})
    if isinstance(ce, dict):
        ce["policyScreened"] = {"allowed_keys": list(screened.keys())}

    workflow_audit.audit_log_node(
        acs,
        "policy_screen",
        duration_ms=(time.perf_counter() - t0) * 1000,
        extra={"screened_keys": list(screened.keys())},
    )
    return {"acs": acs, "screened_updates": screened}


def _node_map_provider(state: EnrichmentState) -> dict[str, Any]:
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    if state.get("failed") or state.get("halt_duplicate"):
        return {"acs": acs}

    norm = state.get("normalized_contact") or {}
    screened = state.get("screened_updates") or {}
    provider = str(norm.get("provider") or "")
    actions: list[dict[str, Any]] = []

    if provider == "followupboss":
        pid = norm.get("person_id")
        if isinstance(pid, int) and isinstance(screened.get("suggested_note"), str) and screened["suggested_note"].strip():
            actions.append(
                {
                    "name": "createNote",
                    "payload": {"personId": pid, "body": screened["suggested_note"].strip()},
                    "effect": "volatile_external",
                }
            )

    meta = acs_state.ensure_metadata(acs)
    meta["outboundActions"] = actions
    ce = meta.setdefault("contactEnrichment", {})
    if isinstance(ce, dict):
        ce["mappedActions"] = len(actions)

    sn2 = screened.get("suggested_note")
    note_ok = isinstance(sn2, str) and bool(sn2.strip())
    workflow_audit.audit_log_node(
        acs,
        "map_provider",
        duration_ms=(time.perf_counter() - t0) * 1000,
        extra={
            "actions": len(actions),
            "person_id": norm.get("person_id"),
            "screened_keys": list(screened.keys()),
            "fub_maps_note_only": True,
            "note_nonempty": note_ok,
        },
    )
    return {"acs": acs}


def _node_send_provider(state: EnrichmentState) -> dict[str, Any]:
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    if state.get("failed") or state.get("halt_duplicate"):
        return {"acs": acs}

    meta = acs_state.ensure_metadata(acs)
    actions = meta.get("outboundActions")
    if not isinstance(actions, list) or not actions:
        workflow_audit.audit_log_node(acs, "send_provider", duration_ms=(time.perf_counter() - t0) * 1000, extra={"skipped": "no_actions"})
        return {"acs": acs}

    uid = _uid(acs)
    if not uid:
        return {"acs": acs}

    if not volatile_external_allowed(acs):
        workflow_audit.audit_log_node(
            acs,
            "send_provider",
            duration_ms=(time.perf_counter() - t0) * 1000,
            extra={"skipped": "volatile_external_not_allowed"},
        )
        ce = meta.setdefault("contactEnrichment", {})
        if isinstance(ce, dict):
            ce["egress"] = {"mode": "skipped_by_policy"}
        return {"acs": acs}

    resp, st = tool_registry.run_tool(
        "integration.apply_followupboss_outbound",
        {"uid": uid, "actions": actions},
        acting_uid=uid,
        acs=acs,
    )
    ce = meta.setdefault("contactEnrichment", {})
    if isinstance(ce, dict):
        ce["egress"] = {"http_status": st, "response": resp}

    workflow_audit.audit_log_node(acs, "send_provider", duration_ms=(time.perf_counter() - t0) * 1000, extra={"http": st})
    return {"acs": acs}


def _node_duplicate_finale(state: EnrichmentState) -> dict[str, Any]:
    acs: dict = state["acs"]
    acs_state.set_core_meta(
        acs,
        {
            "workflow_id": _WORKFLOW_ID,
            "status": "completed",
            "phase": "skipped_duplicate_internal_client",
        },
    )
    workflow_audit.audit_log_node(acs, "duplicate_finale", extra={"reason": "internal_client_exists"})
    workflow_audit.audit_run_finish(acs, status="completed", detail="duplicate")
    return {"acs": acs}


def _node_finalize(state: EnrichmentState) -> dict[str, Any]:
    acs: dict = state["acs"]
    if state.get("halt_duplicate"):
        return {"acs": acs}
    if state.get("failed"):
        acs_state.set_core_meta(acs, {"workflow_id": _WORKFLOW_ID, "status": "failed", "phase": "terminal"})
        workflow_audit.audit_run_finish(acs, status="failed", detail="prior_failure")
        return {"acs": acs}

    acs_state.set_core_meta(acs, {"workflow_id": _WORKFLOW_ID, "status": "completed", "phase": "done"})
    workflow_audit.audit_log_node(acs, "finalize")
    workflow_audit.audit_run_finish(acs, status="completed")
    return {"acs": acs}


def _route_after_internal_check(state: EnrichmentState) -> Literal["duplicate", "continue"]:
    if state.get("failed"):
        return "continue"
    if state.get("halt_duplicate"):
        return "duplicate"
    return "continue"


def build_contact_enrichment_graph():
    g = StateGraph(EnrichmentState)
    g.add_node("load_realtor_profile", _node_load_realtor_profile)
    g.add_node("load_contact", _node_load_contact)
    g.add_node("check_internal_client", _node_check_internal_client)
    g.add_node("normalize", _node_normalize)
    g.add_node("web_research", _node_web_research)
    g.add_node("synthesis", _node_synthesis)
    g.add_node("policy_screen", _node_policy_screen)
    g.add_node("map_provider", _node_map_provider)
    g.add_node("send_provider", _node_send_provider)
    g.add_node("finalize", _node_finalize)
    g.add_node("duplicate_finale", _node_duplicate_finale)

    g.set_entry_point("load_realtor_profile")
    g.add_edge("load_realtor_profile", "load_contact")
    g.add_edge("load_contact", "check_internal_client")
    g.add_conditional_edges(
        "check_internal_client",
        _route_after_internal_check,
        {"duplicate": "duplicate_finale", "continue": "normalize"},
    )
    g.add_edge("normalize", "web_research")
    g.add_edge("web_research", "synthesis")
    g.add_edge("synthesis", "policy_screen")
    g.add_edge("policy_screen", "map_provider")
    g.add_edge("map_provider", "send_provider")
    g.add_edge("send_provider", "finalize")
    g.add_edge("duplicate_finale", END)
    g.add_edge("finalize", END)
    return g.compile()

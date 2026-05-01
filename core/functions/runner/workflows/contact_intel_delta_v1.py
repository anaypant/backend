"""contact.intel_delta_v1 — on peopleUpdated, refresh intel when material fields change (lazy cost)."""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from clients import db_internal, llm_internal
from clients import usage_tracker, web_research_internal
from state import acs_state
from state.execution_policy import volatile_external_allowed
from tools import registry as tool_registry
from workflows import contact_enrichment_v1, normalize_integration_payload, workflow_audit

_logger = logging.getLogger(__name__)

_WORKFLOW_ID = "contact.intel_delta_v1"

_DEFAULT_MATERIAL = ("display_name", "emails", "phones")


class IntelDeltaState(TypedDict, total=False):
    acs: dict[str, Any]
    failed: bool
    realtor_profile: dict[str, Any]
    normalized_contact: dict[str, Any]
    prior_snapshot: dict[str, Any]
    changed_fields: list[str]
    intel_delta_skipped: bool
    intel_delta_did_work: bool
    research: dict[str, Any]
    synthesis_updates: dict[str, Any]
    screened_updates: dict[str, Any]
    budget_mode: str
    token_estimate: dict[str, int]


def _uid(acs: dict) -> str | None:
    u = acs.get("user_id")
    return u.strip() if isinstance(u, str) and u.strip() else None


def _material_keys(realtor_profile: dict[str, Any]) -> tuple[str, ...]:
    cfg = realtor_profile.get("enrichmentConfig") if isinstance(realtor_profile, dict) else None
    if isinstance(cfg, dict):
        raw = cfg.get("deltaMaterialFields")
        if isinstance(raw, list) and raw:
            out = tuple(str(x) for x in raw if isinstance(x, str) and x.strip())
            if out:
                return out
    return _DEFAULT_MATERIAL


def _norm_field(norm: dict[str, Any], key: str) -> Any:
    if key == "display_name":
        return (norm.get("display_name") or "").strip()
    if key == "emails":
        e = norm.get("emails")
        return tuple(sorted(str(x).lower() for x in (e if isinstance(e, list) else []) if isinstance(x, str)))
    if key == "phones":
        p = norm.get("phones")
        return tuple(sorted(str(x) for x in (p if isinstance(p, list) else []) if isinstance(x, str)))
    return norm.get(key)


def _node_load_realtor_profile(state: IntelDeltaState) -> dict[str, Any]:
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    workflow_audit.audit_run_start(acs, _WORKFLOW_ID)
    uid = _uid(acs)
    if not uid:
        acs_state.append_error(acs, "user_id missing")
        acs_state.set_core_meta(acs, {"workflow_id": _WORKFLOW_ID, "status": "failed", "phase": "load_realtor"})
        return {"acs": acs, "failed": True}

    body, st = db_internal.read_document(f"Realtors/{uid}", acting_uid=uid)
    workflow_audit.audit_bump_db_read(acs)
    profile = body.get("data") if isinstance(body.get("data"), dict) else {}
    if st == 404:
        profile = {}
    elif st >= 400:
        acs_state.append_error(acs, f"realtor profile read failed: {st}")
        acs_state.set_core_meta(acs, {"workflow_id": _WORKFLOW_ID, "status": "failed", "phase": "load_realtor"})
        return {"acs": acs, "failed": True}

    meta = acs_state.ensure_metadata(acs)
    meta.setdefault("contactIntelDelta", {})
    if isinstance(meta["contactIntelDelta"], dict):
        meta["contactIntelDelta"]["realtorProfileLoaded"] = True

    workflow_audit.audit_log_node(acs, "load_realtor_profile", duration_ms=(time.perf_counter() - t0) * 1000, extra={"http": st})
    return {"acs": acs, "realtor_profile": profile}


def _node_normalize(state: IntelDeltaState) -> dict[str, Any]:
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    if state.get("failed"):
        return {"acs": acs}
    norm = normalize_integration_payload.normalize_contact(acs)
    meta = acs_state.ensure_metadata(acs)
    mid = meta.setdefault("contactIntelDelta", {})
    if isinstance(mid, dict):
        mid["normalized"] = norm
    workflow_audit.audit_log_node(acs, "normalize", duration_ms=(time.perf_counter() - t0) * 1000)
    return {"acs": acs, "normalized_contact": norm}


def _node_load_baseline_and_gate(state: IntelDeltaState) -> dict[str, Any]:
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    if state.get("failed"):
        return {"acs": acs}

    uid = _uid(acs)
    norm = state.get("normalized_contact") or {}
    rp = state.get("realtor_profile") or {}
    if not uid or not isinstance(norm.get("person_id"), int) or norm["person_id"] <= 0:
        acs_state.append_error(acs, "intel_delta: missing person_id")
        acs_state.set_core_meta(acs, {"workflow_id": _WORKFLOW_ID, "status": "failed", "phase": "baseline"})
        return {"acs": acs, "failed": True}

    doc_id = normalize_integration_payload.internal_client_doc_id(norm)
    path = f"Realtors/{uid}/InternalClients/{doc_id}"
    body, st = db_internal.read_document(path, acting_uid=uid)
    workflow_audit.audit_bump_db_read(acs)

    snap: dict[str, Any] = {}
    if st == 200 and isinstance(body.get("data"), dict):
        ai = body["data"].get("acsIntel")
        if isinstance(ai, dict) and isinstance(ai.get("snapshot"), dict):
            snap = ai["snapshot"]

    def _write_baseline() -> None:
        acs_intel = {
            "snapshot": {
                "display_name": norm.get("display_name"),
                "emails":       norm.get("emails"),
                "phones":       norm.get("phones"),
                "person_id":    norm.get("person_id"),
            },
            "lastEnrichedAt": datetime.now(timezone.utc).isoformat(),
        }
        try:
            db_internal.upsert_merge(
                path,
                {"ownerUid": uid, "createdBy": uid, "acsIntel": acs_intel},
                acting_uid=uid,
                timeout=15,
            )
        except Exception:
            _logger.warning("intel_delta baseline write failed", exc_info=True)

    keys = _material_keys(rp)
    changed: list[str] = []
    if not snap:
        _write_baseline()
        meta = acs_state.ensure_metadata(acs)
        mid = meta.setdefault("contactIntelDelta", {})
        if isinstance(mid, dict):
            mid["skipped"] = "no_prior_snapshot_wrote_baseline"
        workflow_audit.audit_log_node(acs, "load_baseline", duration_ms=(time.perf_counter() - t0) * 1000, extra={"skipped": True})
        return {
            "acs": acs,
            "prior_snapshot": snap,
            "changed_fields": [],
            "intel_delta_skipped": True,
            "intel_delta_did_work": False,
        }

    for k in keys:
        if _norm_field(norm, k) != _norm_field(snap, k):
            changed.append(k)

    if not changed:
        meta = acs_state.ensure_metadata(acs)
        mid = meta.setdefault("contactIntelDelta", {})
        if isinstance(mid, dict):
            mid["skipped"] = "no_material_change"
        workflow_audit.audit_log_node(acs, "load_baseline", duration_ms=(time.perf_counter() - t0) * 1000, extra={"skipped": True})
        return {
            "acs": acs,
            "prior_snapshot": snap,
            "changed_fields": [],
            "intel_delta_skipped": True,
            "intel_delta_did_work": False,
        }

    workflow_audit.audit_log_node(
        acs, "load_baseline", duration_ms=(time.perf_counter() - t0) * 1000, extra={"changed": changed}
    )
    return {
        "acs": acs,
        "prior_snapshot": snap,
        "changed_fields": changed,
        "intel_delta_skipped": False,
        "intel_delta_did_work": True,
    }


def _node_web_research(state: IntelDeltaState) -> dict[str, Any]:
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    if state.get("failed") or state.get("intel_delta_skipped"):
        return {"acs": acs}

    norm = state.get("normalized_contact") or {}
    uid = _uid(acs) or ""
    rp = state.get("realtor_profile") or {}
    emails = norm.get("emails") if isinstance(norm.get("emails"), list) else []
    _, _, biz_domain = contact_enrichment_v1._extract_business_email(emails)
    company_name = contact_enrichment_v1._company_name_from_domain(biz_domain) if biz_domain else ""
    display_name = (norm.get("display_name") or "").strip()

    if display_name and company_name:
        query = f"{display_name} {company_name}"
    elif display_name:
        query = display_name
    else:
        query = f"id={norm.get('external_person_id') or 'unknown'}"

    seed_urls = [f"https://{biz_domain}"] if biz_domain else []

    mode, budget_usd, spent_usd, _ = usage_tracker.check_mode(uid, realtor_profile=rp)
    # Delta runs: avoid paid search backends; lazy pipeline may still scrape seed URLs.
    force_backend = "duckduckgo"

    res, st = web_research_internal.research_query_to_summary(
        query,
        result_limit=2,
        seed_urls=seed_urls,
        force_backend=force_backend,
        lazy=True,
    )
    for _ in range(max(1, int(res.get("llm_calls") or 1))):
        workflow_audit.audit_bump_llm(acs)

    tok_in = int(res.get("tokens_in") or 0)
    tok_out = int(res.get("tokens_out") or 0)
    tok_est = {
        "in": tok_in,
        "out": tok_out,
        "search_calls": int(res.get("search_calls") or 0),
    }

    meta = acs_state.ensure_metadata(acs)
    mid = meta.setdefault("contactIntelDelta", {})
    if isinstance(mid, dict):
        mid["webResearch"] = {
            "http_status": st,
            "mode": res.get("mode"),
            "query": query,
            "changed_fields": state.get("changed_fields") or [],
            "budget_mode": mode,
            "spent_usd": round(spent_usd, 4),
            "budget_usd": round(budget_usd, 2),
        }

    if st >= 400:
        acs_state.append_error(acs, f"intel_delta web_research failed: {st}")
        acs_state.set_core_meta(acs, {"workflow_id": _WORKFLOW_ID, "status": "failed", "phase": "web_research"})
        return {"acs": acs, "failed": True, "research": res, "budget_mode": mode, "token_estimate": tok_est}

    workflow_audit.audit_log_node(acs, "web_research", duration_ms=(time.perf_counter() - t0) * 1000, extra={"http": st})
    return {"acs": acs, "research": res, "budget_mode": mode, "token_estimate": tok_est}


def _node_synthesis(state: IntelDeltaState) -> dict[str, Any]:
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    if state.get("failed") or state.get("intel_delta_skipped"):
        return {"acs": acs}

    norm = state.get("normalized_contact") or {}
    research = state.get("research") or {}
    changed = state.get("changed_fields") or []
    prior = state.get("prior_snapshot") or {}
    pid = norm.get("person_id")
    must_note = isinstance(pid, int) and pid > 0 and norm.get("provider") == "followupboss"

    schema = (
        "Return JSON only with keys: "
        "updates (object with suggested_note string), confidence (string), rationale (string). "
        "suggested_note must start with \"ACS update — \" and be 2-5 sentences. "
        f"Explain that these fields changed in Follow Up Boss: {', '.join(changed)}. "
        "Summarize refreshed context from research_summary; if sparse, say what is still unknown. "
        "This person is a buyer/seller client, not a realtor."
        if must_note
        else "Return JSON only: updates object (may be empty), confidence, rationale."
    )
    messages = [
        {
            "role": "user",
            "content": json.dumps(
                {
                    "normalized_contact": norm,
                    "prior_snapshot": prior,
                    "changed_fields": changed,
                    "research_summary": research.get("summary"),
                    "research_sources": research.get("sources"),
                    "instruction": schema,
                },
                default=str,
            )[:80_000],
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
        acs_state.append_error(acs, f"intel_delta synthesis error: {e!s}")
        acs_state.set_core_meta(acs, {"workflow_id": _WORKFLOW_ID, "status": "failed", "phase": "synthesis"})
        return {"acs": acs, "failed": True}

    workflow_audit.audit_bump_llm(acs)
    if st >= 400:
        acs_state.append_error(acs, f"intel_delta synthesis http {st}")
        acs_state.set_core_meta(acs, {"workflow_id": _WORKFLOW_ID, "status": "failed", "phase": "synthesis"})
        return {"acs": acs, "failed": True}

    raw = body.get("text") if isinstance(body.get("text"), str) else ""
    updates: dict[str, Any] = {}
    coercion = "empty_body"
    try:
        parsed = json.loads(raw) if raw.strip() else {}
        if isinstance(parsed, dict):
            updates, coercion = contact_enrichment_v1._coerce_synthesis_updates(parsed)
        else:
            updates, coercion = {}, "not_object_json"
    except json.JSONDecodeError:
        updates = {}
        coercion = "json_decode_error"

    sn0 = updates.get("suggested_note")
    if must_note and (not isinstance(sn0, str) or not sn0.strip()):
        summary = (research.get("summary") or "").strip()
        if summary:
            updates["suggested_note"] = (
                f"ACS update — Follow Up Boss fields changed ({', '.join(changed)}). "
                f"Refreshed context: {summary[:900]}"
            )
        else:
            updates["suggested_note"] = (
                f"ACS update — {', '.join(changed)} changed in Follow Up Boss. "
                "Intel was refreshed; little additional public context was found."
            )

    prior_tok = state.get("token_estimate") or {"in": 0, "out": 0, "search_calls": 0}
    token_estimate = {
        "in": prior_tok.get("in", 0) + len(json.dumps(messages)) // 4,
        "out": prior_tok.get("out", 0) + len(raw) // 4,
        "search_calls": prior_tok.get("search_calls", 0),
    }

    meta = acs_state.ensure_metadata(acs)
    mid = meta.setdefault("contactIntelDelta", {})
    if isinstance(mid, dict):
        mid["synthesis"] = {"http_status": st, "keys": list(updates.keys()), "coercion": coercion}

    workflow_audit.audit_log_node(acs, "synthesis", duration_ms=(time.perf_counter() - t0) * 1000)
    return {"acs": acs, "synthesis_updates": updates, "token_estimate": token_estimate}


def _node_policy_screen(state: IntelDeltaState) -> dict[str, Any]:
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    if state.get("failed"):
        return {"acs": acs}

    raw_updates = state.get("synthesis_updates") or {}
    allowed_top = {"suggested_note", "tags", "custom_fields"}
    screened: dict[str, Any] = {}
    for k, v in raw_updates.items():
        if k not in allowed_top:
            continue
        if k == "suggested_note" and isinstance(v, str):
            note = contact_enrichment_v1._redact_string(v)[:8000]
            screened[k] = note
        elif k == "tags" and isinstance(v, list):
            screened[k] = [str(x)[:120] for x in v[:25] if isinstance(x, (str, int, float))]
        elif k == "custom_fields" and isinstance(v, dict):
            cf: dict[str, str] = {}
            for ck, cv in list(v.items())[:40]:
                if isinstance(ck, str) and isinstance(cv, (str, int, float)):
                    cf[ck[:80]] = contact_enrichment_v1._redact_string(str(cv))[:2000]
            screened[k] = cf

    meta = acs_state.ensure_metadata(acs)
    mid = meta.setdefault("contactIntelDelta", {})
    if isinstance(mid, dict):
        mid["policyScreened"] = {"allowed_keys": list(screened.keys())}

    workflow_audit.audit_log_node(
        acs,
        "policy_screen",
        duration_ms=(time.perf_counter() - t0) * 1000,
        extra={"screened_keys": list(screened.keys())},
    )
    return {"acs": acs, "screened_updates": screened}


def _node_map_provider(state: IntelDeltaState) -> dict[str, Any]:
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    if state.get("failed"):
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
    mid = meta.setdefault("contactIntelDelta", {})
    if isinstance(mid, dict):
        mid["mappedActions"] = len(actions)

    sn2 = screened.get("suggested_note")
    note_ok = isinstance(sn2, str) and bool(sn2.strip())
    workflow_audit.audit_log_node(
        acs,
        "map_provider",
        duration_ms=(time.perf_counter() - t0) * 1000,
        extra={"actions": len(actions), "person_id": norm.get("person_id"), "note_nonempty": note_ok},
    )
    return {"acs": acs}


def _node_send_provider(state: IntelDeltaState) -> dict[str, Any]:
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    if state.get("failed"):
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
        mid = meta.setdefault("contactIntelDelta", {})
        if isinstance(mid, dict):
            mid["egress"] = {"mode": "skipped_by_policy"}
        return {"acs": acs}

    resp, st = tool_registry.run_tool(
        "integration.apply_followupboss_outbound",
        {"uid": uid, "actions": actions},
        acting_uid=uid,
        acs=acs,
    )
    mid = meta.setdefault("contactIntelDelta", {})
    if isinstance(mid, dict):
        mid["egress"] = {"http_status": st, "response": resp}

    workflow_audit.audit_log_node(acs, "send_provider", duration_ms=(time.perf_counter() - t0) * 1000, extra={"http": st})
    return {"acs": acs}


def _node_persist_intel(state: IntelDeltaState) -> dict[str, Any]:
    acs: dict = state["acs"]
    if state.get("failed") or not state.get("intel_delta_did_work"):
        return {"acs": acs}
    uid = _uid(acs)
    norm = state.get("normalized_contact") or {}
    research = state.get("research") or {}
    if not uid or not isinstance(norm.get("person_id"), int):
        return {"acs": acs}

    doc_id = normalize_integration_payload.internal_client_doc_id(norm)
    path = f"Realtors/{uid}/InternalClients/{doc_id}"
    acs_intel = {
        "snapshot": {
            "display_name": norm.get("display_name"),
            "emails":       norm.get("emails"),
            "phones":       norm.get("phones"),
            "person_id":    norm.get("person_id"),
        },
        "lastWebSummary":     (research.get("summary") or "")[:4000],
        "lastEnrichmentTier": "intel_delta",
        "lastEnrichedAt":     datetime.now(timezone.utc).isoformat(),
    }
    try:
        db_internal.upsert_merge(path, {"ownerUid": uid, "acsIntel": acs_intel}, acting_uid=uid, timeout=15)
    except Exception:
        _logger.warning("intel_delta persist failed", exc_info=True)
    return {"acs": acs}


def _node_record_usage(state: IntelDeltaState) -> dict[str, Any]:
    acs: dict = state["acs"]
    if state.get("failed") or not state.get("intel_delta_did_work"):
        return {"acs": acs}

    uid = _uid(acs)
    if not uid:
        return {"acs": acs}

    tok = state.get("token_estimate") or {}
    mode = state.get("budget_mode") or "premium"
    meta = acs_state.ensure_metadata(acs)
    mid = meta.setdefault("contactIntelDelta", {})
    if not isinstance(mid, dict):
        mid = {}
        meta["contactIntelDelta"] = mid
    wr = mid.get("webResearch") or {}
    pipe = (state.get("research") or {}).get("pipeline") or {}
    be = pipe.get("search_backend") or wr.get("search_backend") or "duckduckgo"

    budget_usd, _ = usage_tracker.get_budget_config(uid, state.get("realtor_profile"))
    raw_cost = usage_tracker.record_workflow_run(
        uid,
        workflow_id=_WORKFLOW_ID,
        usage_tier="intel_delta",
        mode=mode,
        search_backend=str(be),
        tokens_in=int(tok.get("in") or 0),
        tokens_out=int(tok.get("out") or 0),
        search_calls=int(tok.get("search_calls") or 0),
        budget_usd=budget_usd,
    )
    if isinstance(mid, dict):
        mid["usageRecorded"] = {"raw_cost_usd": round(raw_cost, 6), "usage_tier": "intel_delta"}
    return {"acs": acs}


def _node_finalize(state: IntelDeltaState) -> dict[str, Any]:
    acs: dict = state["acs"]
    if state.get("failed"):
        acs_state.set_core_meta(acs, {"workflow_id": _WORKFLOW_ID, "status": "failed", "phase": "terminal"})
        workflow_audit.audit_run_finish(acs, status="failed", detail="failure")
        return {"acs": acs}
    acs_state.set_core_meta(acs, {"workflow_id": _WORKFLOW_ID, "status": "completed", "phase": "done"})
    workflow_audit.audit_log_node(acs, "finalize")
    workflow_audit.audit_run_finish(acs, status="completed")
    return {"acs": acs}


def build_contact_intel_delta_graph():
    g = StateGraph(IntelDeltaState)
    g.add_node("load_realtor_profile", _node_load_realtor_profile)
    g.add_node("normalize", _node_normalize)
    g.add_node("load_baseline", _node_load_baseline_and_gate)
    g.add_node("web_research", _node_web_research)
    g.add_node("synthesis", _node_synthesis)
    g.add_node("policy_screen", _node_policy_screen)
    g.add_node("map_provider", _node_map_provider)
    g.add_node("send_provider", _node_send_provider)
    g.add_node("persist_intel", _node_persist_intel)
    g.add_node("record_usage", _node_record_usage)
    g.add_node("finalize", _node_finalize)

    g.set_entry_point("load_realtor_profile")
    g.add_edge("load_realtor_profile", "normalize")
    g.add_edge("normalize", "load_baseline")
    g.add_edge("load_baseline", "web_research")
    g.add_edge("web_research", "synthesis")
    g.add_edge("synthesis", "policy_screen")
    g.add_edge("policy_screen", "map_provider")
    g.add_edge("map_provider", "send_provider")
    g.add_edge("send_provider", "persist_intel")
    g.add_edge("persist_intel", "record_usage")
    g.add_edge("record_usage", "finalize")
    g.add_edge("finalize", END)
    return g.compile()

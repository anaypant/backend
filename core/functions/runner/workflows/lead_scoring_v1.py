"""lead.scoring_v1 — score a lead deterministically + qualitatively and store the result."""

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
from workflows import normalize_integration_payload, workflow_audit
from workflows.migrations.schemas.lead_internal_v1 import canonical_lead_id as _make_canonical_lead_id

_logger = logging.getLogger(__name__)

_WORKFLOW_ID = "lead.scoring_v1"

# Weights used for deterministic scoring (max 60 pts).
_DEFAULT_HOT_THRESHOLD = 70


class LeadScoringState(TypedDict, total=False):
    acs: dict[str, Any]
    failed: bool
    realtor_profile: dict[str, Any]
    glyde_settings: dict[str, Any]
    lead: dict[str, Any]
    acs_intel: dict[str, Any] | None
    canonical_lead_id: str
    deterministic_score: int
    llm_score: int
    final_score: int
    is_hot: bool


def _uid(acs: dict) -> str | None:
    u = acs.get("user_id")
    return u.strip() if isinstance(u, str) and u.strip() else None


def _iso_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _node_load_realtor_profile(state: LeadScoringState) -> dict[str, Any]:
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    workflow_audit.audit_run_start(acs, _WORKFLOW_ID)

    uid = _uid(acs)
    if not uid:
        acs_state.append_error(acs, "user_id missing")
        acs_state.set_core_meta(acs, {"workflow_id": _WORKFLOW_ID, "status": "failed", "phase": "load_realtor"})
        workflow_audit.audit_log_node(acs, "load_realtor_profile", duration_ms=(time.perf_counter() - t0) * 1000, extra={"error": "no_uid"})
        return {"acs": acs, "failed": True}

    profile_body, pst = db_internal.read_document(f"Realtors/{uid}", acting_uid=uid)
    workflow_audit.audit_bump_db_read(acs)
    profile = profile_body.get("data") if isinstance(profile_body.get("data"), dict) else {}

    settings_body, sst = db_internal.read_document(f"Realtors/{uid}/GlydeSettings/config", acting_uid=uid)
    workflow_audit.audit_bump_db_read(acs)
    settings = settings_body.get("data") if isinstance(settings_body.get("data"), dict) else {}

    workflow_audit.audit_log_node(acs, "load_realtor_profile", duration_ms=(time.perf_counter() - t0) * 1000, extra={"profile_http": pst, "settings_http": sst})
    return {"acs": acs, "failed": False, "realtor_profile": profile, "glyde_settings": settings}


def _node_load_lead(state: LeadScoringState) -> dict[str, Any]:
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    if state.get("failed"):
        return {"acs": acs}

    uid = _uid(acs)
    payload = acs.get("payload") if isinstance(acs.get("payload"), dict) else {}

    # Support both "person" (standard) and "fubPerson" (webhook alias used by FUB integration events).
    person = payload.get("person") if isinstance(payload.get("person"), dict) else {}
    if not person:
        person = payload.get("fubPerson") if isinstance(payload.get("fubPerson"), dict) else {}
    if not person:
        person = payload

    person_id = (
        person.get("id")
        or person.get("personId")
        or payload.get("personId")
        or payload.get("id")
    )

    # Use the same canonical ID format as import_leads_v1 / lead_internal_v1 so that
    # leads synced from FUB can be loaded by this workflow (was: "fub_{id}", now "followupboss_{id}").
    source_provider = str(
        (acs.get("source") or {}).get("provider") or "followupboss"
    ).strip().lower() or "followupboss"
    cid = _make_canonical_lead_id(source_provider, str(person_id)) if person_id else f"lead_{uuid.uuid4()}"

    lead: dict[str, Any] = dict(person)

    if uid and person_id:
        lead_body, lst = db_internal.read_document(f"Realtors/{uid}/Leads/{cid}", acting_uid=uid)
        workflow_audit.audit_bump_db_read(acs)
        if lst == 200 and isinstance(lead_body.get("data"), dict):
            stored = lead_body["data"]
            stored_lead = stored.get("lead") if isinstance(stored.get("lead"), dict) else stored
            lead.update(stored_lead)

    # Alias internal-schema field names to the names the rest of this workflow expects,
    # so that leads imported via migration.import_leads_v1 score correctly.
    if "displayName" in lead and "name" not in lead:
        lead["name"] = lead["displayName"]
    if "stageLabel" in lead and "stage" not in lead:
        lead["stage"] = lead["stageLabel"]
    if "sourceLabel" in lead and "source" not in lead:
        lead["source"] = lead["sourceLabel"]
    if "primaryEmail" in lead and "emails" not in lead:
        pe = lead["primaryEmail"]
        lead["emails"] = [pe] if isinstance(pe, str) and pe else []
    if "primaryPhone" in lead and "phones" not in lead:
        pp = lead["primaryPhone"]
        lead["phones"] = [pp] if isinstance(pp, str) and pp else []

    workflow_audit.audit_log_node(acs, "load_lead", duration_ms=(time.perf_counter() - t0) * 1000, extra={"canonical_id": cid})
    return {"acs": acs, "lead": lead, "canonical_lead_id": cid}


def _node_load_acs_intel(state: LeadScoringState) -> dict[str, Any]:
    """Load Realtors/{{uid}}/InternalClients/* acsIntel for scoring context (enrichment + delta)."""
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    if state.get("failed"):
        return {"acs": acs, "acs_intel": None}

    uid = _uid(acs)
    if not uid:
        return {"acs": acs, "acs_intel": None}

    try:
        norm = normalize_integration_payload.normalize_contact(acs)
    except Exception as e:
        _logger.debug("load_acs_intel: normalize skipped: %s", e)
        return {"acs": acs, "acs_intel": None}

    doc_id = normalize_integration_payload.internal_client_doc_id(norm)
    path = f"Realtors/{uid}/InternalClients/{doc_id}"
    body, st = db_internal.read_document(path, acting_uid=uid)
    workflow_audit.audit_bump_db_read(acs)

    meta = acs_state.ensure_metadata(acs)
    ls = meta.setdefault("leadScoring", {})
    if st != 200 or not isinstance(body.get("data"), dict):
        if isinstance(ls, dict):
            ls["acsIntel"] = {"loaded": False, "http": st, "path": path}
        workflow_audit.audit_log_node(acs, "load_acs_intel", duration_ms=(time.perf_counter() - t0) * 1000, extra={"http": st})
        return {"acs": acs, "acs_intel": None}

    data = body["data"]
    ai = data.get("acsIntel") if isinstance(data.get("acsIntel"), dict) else None
    if isinstance(ls, dict):
        summary = str((ai or {}).get("lastWebSummary") or "")
        ls["acsIntel"] = {
            "loaded": bool(ai),
            "http": st,
            "tier": (ai or {}).get("lastEnrichmentTier"),
            "enriched_at": (ai or {}).get("lastEnrichedAt"),
            "summary_len": len(summary),
        }

    workflow_audit.audit_log_node(acs, "load_acs_intel", duration_ms=(time.perf_counter() - t0) * 1000, extra={"http": st, "has_intel": bool(ai)})
    return {"acs": acs, "acs_intel": ai}


def _days_since(date_str: str | None) -> int | None:
    if not date_str:
        return None
    try:
        dt = datetime.datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        now = datetime.datetime.now(datetime.timezone.utc)
        delta = now - dt.astimezone(datetime.timezone.utc)
        return max(0, delta.days)
    except (ValueError, TypeError):
        return None


def _node_compute_deterministic_score(state: LeadScoringState) -> dict[str, Any]:
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    if state.get("failed"):
        return {"acs": acs}

    lead = state.get("lead") or {}
    score = 0
    reasons: list[str] = []

    emails = lead.get("emails") or lead.get("email")
    phones = lead.get("phones") or lead.get("phone")
    has_email = bool(emails)
    has_phone = bool(phones)

    if has_email:
        score += 8
        reasons.append("has_email+8")
    if has_phone:
        score += 8
        reasons.append("has_phone+8")

    stage = str(lead.get("stage") or lead.get("pipelineStage") or "").lower()
    stage_map = {
        "active buyer": 20, "active seller": 20, "hot": 18, "warm": 12,
        "contract": 15, "closed": 5, "inactive": -5, "cold": -3, "lost": -8,
    }
    for key, pts in stage_map.items():
        if key in stage:
            score += pts
            reasons.append(f"stage:{key}{pts:+d}")
            break

    tags = lead.get("tags") if isinstance(lead.get("tags"), list) else []
    tag_str = " ".join(str(t).lower() for t in tags)
    if "hot" in tag_str:
        score += 15
        reasons.append("tag:hot+15")
    elif "warm" in tag_str:
        score += 8
        reasons.append("tag:warm+8")
    elif "cold" in tag_str or "archive" in tag_str:
        score -= 5
        reasons.append("tag:cold-5")

    last_contacted = lead.get("lastContacted") or lead.get("lastActivityAt")
    days = _days_since(last_contacted)
    if days is not None:
        if days <= 7:
            score += 10
            reasons.append("recent_contact<=7d+10")
        elif days <= 30:
            score += 5
            reasons.append("recent_contact<=30d+5")
        elif days > 90:
            score -= 8
            reasons.append("inactive>90d-8")

    source = str(lead.get("source") or lead.get("leadSource") or "").lower()
    if any(s in source for s in ("paid", "ppc", "google", "meta", "facebook", "zillow")):
        score += 8
        reasons.append("paid_source+8")
    elif any(s in source for s in ("referral", "organic")):
        score += 4
        reasons.append("organic_source+4")

    intel = state.get("acs_intel") or {}
    summary = str(intel.get("lastWebSummary") or "").strip()
    if len(summary) > 200:
        score = min(60, score + 3)
        reasons.append("acs_intel_summary+3")

    score = max(0, min(60, score))

    meta = acs_state.ensure_metadata(acs)
    meta.setdefault("leadScoring", {})
    if isinstance(meta["leadScoring"], dict):
        meta["leadScoring"]["deterministic"] = {"score": score, "reasons": reasons}

    workflow_audit.audit_log_node(
        acs,
        "compute_deterministic_score",
        duration_ms=(time.perf_counter() - t0) * 1000,
        extra={"score": score, "reasons_count": len(reasons)},
    )
    return {"acs": acs, "deterministic_score": score}


def _node_llm_qualitative_score(state: LeadScoringState) -> dict[str, Any]:
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    if state.get("failed"):
        return {"acs": acs, "llm_score": 20}

    lead = state.get("lead") or {}

    # Skip the LLM call when the lead is too sparse to reason about — avoids hallucinated rationale.
    # "Meaningful" keys are non-empty, non-None values that carry signal.
    _SIGNAL_KEYS = ("emails", "phones", "primaryEmail", "primaryPhone", "stage", "stageLabel",
                    "tags", "notes", "source", "sourceLabel", "lastContacted", "lastActivityAt",
                    "price", "background", "properties", "status")
    signal_count = sum(1 for k in _SIGNAL_KEYS if lead.get(k))
    intel = state.get("acs_intel") or {}
    intel_summary = str(intel.get("lastWebSummary") or "").strip()
    if len(intel_summary) > 120:
        signal_count += 2

    if signal_count < 2:
        meta = acs_state.ensure_metadata(acs)
        meta.setdefault("leadScoring", {})
        if isinstance(meta["leadScoring"], dict):
            meta["leadScoring"]["llm"] = {
                "score": 10,
                "rationale": "Insufficient lead data for qualitative scoring. Provide contact info, stage, or notes to improve accuracy.",
            }
        workflow_audit.audit_log_node(acs, "llm_qualitative_score", duration_ms=(time.perf_counter() - t0) * 1000, extra={"llm_score": 10, "skipped": "sparse_lead"})
        return {"acs": acs, "llm_score": 10}

    # Include both raw FUB-style keys AND internal-schema aliases so either path gives the LLM data.
    _LLM_KEYS = (
        "name", "displayName", "firstName", "lastName",
        "emails", "phones", "primaryEmail", "primaryPhone",
        "tags", "stage", "stageLabel", "notes",
        "source", "sourceLabel", "lastContacted", "lastActivityAt",
        "properties", "background", "status", "price", "timeframe",
        "givenName", "familyName",
    )
    ai = state.get("acs_intel") or {}
    acs_intel_context = None
    if isinstance(ai, dict) and ai:
        acs_intel_context = {
            "last_web_summary": str(ai.get("lastWebSummary") or "")[:3000],
            "tier": ai.get("lastEnrichmentTier"),
            "as_of": ai.get("lastEnrichedAt"),
        }

    messages = [
        {
            "role": "user",
            "content": json.dumps(
                {
                    "lead": {k: lead[k] for k in _LLM_KEYS if k in lead},
                    "acs_intel_context": acs_intel_context,
                    "instruction": (
                        "Score this real estate lead on a scale of 0-40 based on conversion likelihood. "
                        "Consider: engagement signals (recency, response time), notes content, "
                        "stated budget and requirements, property interests, background, stage, source. "
                        "When acs_intel_context is present, treat last_web_summary as supplementary "
                        "open-web / ACS research context (not the lead's own words); weigh it lightly and note uncertainty. "
                        "Return JSON only: "
                        "{\"score\": <int 0-40>, \"rationale\": <string under 500 chars, be specific and actionable>}"
                    ),
                },
                default=str,
            )[:40_000],
        }
    ]

    llm_score = 20
    try:
        body, st = llm_internal.complete(
            model=(os.environ.get("ACS_SCORING_LLM_MODEL") or "openai/gpt-4o-mini").strip(),
            messages=messages,
            response_format="json",
        )
        workflow_audit.audit_bump_llm(acs)
        if st < 400:
            raw = body.get("text") or body.get("json") or ""
            try:
                parsed = json.loads(raw) if isinstance(raw, str) else (raw if isinstance(raw, dict) else {})
                s = int(parsed.get("score") or 20)
                llm_score = max(0, min(40, s))
                meta = acs_state.ensure_metadata(acs)
                meta.setdefault("leadScoring", {})
                if isinstance(meta["leadScoring"], dict):
                    meta["leadScoring"]["llm"] = {
                        "score": llm_score,
                        "rationale": str(parsed.get("rationale") or "")[:500],
                    }
            except (json.JSONDecodeError, ValueError, TypeError):
                pass
    except Exception as e:
        acs_state.append_error(acs, f"lead scoring llm error (non-fatal): {e!s}")

    workflow_audit.audit_log_node(acs, "llm_qualitative_score", duration_ms=(time.perf_counter() - t0) * 1000, extra={"llm_score": llm_score})
    return {"acs": acs, "llm_score": llm_score}


def _node_merge_scores(state: LeadScoringState) -> dict[str, Any]:
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    if state.get("failed"):
        return {"acs": acs}

    d_score = state.get("deterministic_score") or 0
    l_score = state.get("llm_score") or 20
    final = max(0, min(100, d_score + l_score))

    settings = state.get("glyde_settings") or {}
    threshold = int(settings.get("hotLeadThreshold") or _DEFAULT_HOT_THRESHOLD)
    is_hot = final >= threshold

    meta = acs_state.ensure_metadata(acs)
    meta.setdefault("leadScoring", {})
    if isinstance(meta["leadScoring"], dict):
        meta["leadScoring"]["final"] = {"score": final, "threshold": threshold, "is_hot": is_hot}

    workflow_audit.audit_log_node(acs, "merge_scores", duration_ms=(time.perf_counter() - t0) * 1000, extra={"final": final, "is_hot": is_hot})
    return {"acs": acs, "final_score": final, "is_hot": is_hot}


def _node_store_score(state: LeadScoringState) -> dict[str, Any]:
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    if state.get("failed"):
        return {"acs": acs}

    uid = _uid(acs)
    if not uid:
        return {"acs": acs}

    canonical_id = state.get("canonical_lead_id") or ""
    if not canonical_id:
        workflow_audit.audit_log_node(acs, "store_score", duration_ms=(time.perf_counter() - t0) * 1000, extra={"skipped": "no_canonical_id"})
        return {"acs": acs}

    final = state.get("final_score") or 0
    is_hot = bool(state.get("is_hot"))
    # ownerUid is required so that hot_leads_v1's Firestore query (filter: ownerUid == uid) can find this lead.
    _, st = db_internal.upsert_merge(
        f"Realtors/{uid}/Leads/{canonical_id}",
        {
            "ownerUid": uid,
            "glydeScore": final,
            "glydeScoreUpdatedAt": _iso_now(),
            "glydeIsHot": is_hot,
        },
        acting_uid=uid,
    )

    workflow_audit.audit_log_node(acs, "store_score", duration_ms=(time.perf_counter() - t0) * 1000, extra={"http": st, "score": final})
    return {"acs": acs}


def _node_check_hot_threshold(state: LeadScoringState) -> dict[str, Any]:
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    if state.get("failed") or not state.get("is_hot"):
        workflow_audit.audit_log_node(acs, "check_hot_threshold", duration_ms=(time.perf_counter() - t0) * 1000, extra={"is_hot": False})
        return {"acs": acs}

    uid = _uid(acs)
    if not uid:
        return {"acs": acs}

    lead = state.get("lead") or {}
    final = state.get("final_score") or 0
    lead_name = (
        lead.get("name") or lead.get("displayName")
        or lead.get("firstName") or "Lead"
    )

    # Pull LLM rationale to give the realtor context in the notification.
    meta_check = acs_state.ensure_metadata(acs)
    llm_rationale = ""
    scoring_meta = meta_check.get("leadScoring") if isinstance(meta_check.get("leadScoring"), dict) else {}
    llm_meta = scoring_meta.get("llm") if isinstance(scoring_meta.get("llm"), dict) else {}
    llm_rationale = str(llm_meta.get("rationale") or "").strip()

    body_text = f"{lead_name} scored {final}/100."
    if llm_rationale:
        body_text += f" {llm_rationale[:300]}"
    body_text += " Review and prioritize."

    notif_id = str(uuid.uuid4())
    notif: dict[str, Any] = {
        "ownerUid": uid,
        "title": f"Hot lead: {lead_name}",
        "body": body_text,
        "severity": "info",
        "createdAt": _iso_now(),
        "source": _WORKFLOW_ID,
        "canonicalLeadId": state.get("canonical_lead_id") or "",
        "glydeScore": final,
        "llmRationale": llm_rationale[:500],
    }
    _, st = db_internal.upsert_merge(f"Realtors/{uid}/Notifications/{notif_id}", notif, acting_uid=uid)

    workflow_audit.audit_log_node(acs, "check_hot_threshold", duration_ms=(time.perf_counter() - t0) * 1000, extra={"notif_http": st, "score": final})
    return {"acs": acs}


def _node_finalize(state: LeadScoringState) -> dict[str, Any]:
    acs: dict = state["acs"]
    if state.get("failed"):
        acs_state.set_core_meta(acs, {"workflow_id": _WORKFLOW_ID, "status": "failed", "phase": "terminal"})
        workflow_audit.audit_run_finish(acs, status="failed", detail="prior_failure")
    else:
        acs_state.set_core_meta(acs, {"workflow_id": _WORKFLOW_ID, "status": "completed", "phase": "done"})
        workflow_audit.audit_log_node(acs, "finalize")
        workflow_audit.audit_run_finish(acs, status="completed")
    return {"acs": acs}


def build_lead_scoring_graph():
    g = StateGraph(LeadScoringState)
    g.add_node("load_realtor_profile", _node_load_realtor_profile)
    g.add_node("load_lead", _node_load_lead)
    g.add_node("load_acs_intel", _node_load_acs_intel)
    g.add_node("compute_deterministic_score", _node_compute_deterministic_score)
    g.add_node("llm_qualitative_score", _node_llm_qualitative_score)
    g.add_node("merge_scores", _node_merge_scores)
    g.add_node("store_score", _node_store_score)
    g.add_node("check_hot_threshold", _node_check_hot_threshold)
    g.add_node("finalize", _node_finalize)

    g.set_entry_point("load_realtor_profile")
    g.add_edge("load_realtor_profile", "load_lead")
    g.add_edge("load_lead", "load_acs_intel")
    g.add_edge("load_acs_intel", "compute_deterministic_score")
    g.add_edge("compute_deterministic_score", "llm_qualitative_score")
    g.add_edge("llm_qualitative_score", "merge_scores")
    g.add_edge("merge_scores", "store_score")
    g.add_edge("store_score", "check_hot_threshold")
    g.add_edge("check_hot_threshold", "finalize")
    g.add_edge("finalize", END)
    return g.compile()

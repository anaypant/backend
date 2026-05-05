"""contact.enrichment_v1 — load profile/contact, normalize, research, synthesize, policy, map, optional egress."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Literal, TypedDict

from langgraph.graph import END, StateGraph

from clients import db_internal, llm_internal
from clients import usage_tracker, web_research_internal
from state import acs_state
from state.execution_policy import volatile_external_allowed
from tools import registry as tool_registry
from workflows import normalize_integration_payload, workflow_audit
from workflows.migrations.schemas.lead_internal_v1 import canonical_lead_id as _canonical_lead_id

_logger = logging.getLogger(__name__)

_WORKFLOW_ID = "contact.enrichment_v1"


class EnrichmentState(TypedDict, total=False):
    acs: dict[str, Any]
    failed: bool
    halt_duplicate: bool
    realtor_profile: dict[str, Any]
    raw_contact: dict[str, Any]
    normalized_contact: dict[str, Any]
    glyde_lead_lane: str
    research: dict[str, Any]
    synthesis_updates: dict[str, Any]
    screened_updates: dict[str, Any]
    budget_mode: str            # "premium" | "standard"
    enrichment_tier: str        # "lazy" | "full"
    token_estimate: dict[str, int]  # {"in": N, "out": N, "search_calls": N}


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


def _node_load_glyde_lead_lane(state: EnrichmentState) -> dict[str, Any]:
    """Read ``glydeLeadLane`` from ``Leads/{canonical}`` for nurture intel gating."""
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    if state.get("failed") or state.get("halt_duplicate"):
        return {"acs": acs, "glyde_lead_lane": "active"}

    uid = _uid(acs)
    norm = state.get("normalized_contact") or {}
    pid = norm.get("person_id")
    prov = str(norm.get("provider") or "followupboss").strip().lower() or "followupboss"
    lane = "active"
    if uid and isinstance(pid, int) and pid > 0:
        cid = _canonical_lead_id(prov, str(pid))
        body, st = db_internal.read_document(f"Realtors/{uid}/Leads/{cid}", acting_uid=uid)
        workflow_audit.audit_bump_db_read(acs)
        if st == 200 and isinstance(body.get("data"), dict):
            raw = str(body["data"].get("glydeLeadLane") or "active").lower()
            if raw in ("active", "nurture"):
                lane = raw

    meta = acs_state.ensure_metadata(acs)
    ce = meta.setdefault("contactEnrichment", {})
    if isinstance(ce, dict):
        ce["glydeLeadLane"] = lane

    workflow_audit.audit_log_node(
        acs,
        "load_glyde_lead_lane",
        duration_ms=(time.perf_counter() - t0) * 1000,
        extra={"lane": lane},
    )
    return {"acs": acs, "glyde_lead_lane": lane}


def _node_classify_enrichment_tier(state: EnrichmentState) -> dict[str, Any]:
    """Choose lazy vs full snapshot enrichment (deterministic; no extra LLM)."""
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    if state.get("failed") or state.get("halt_duplicate"):
        return {"acs": acs}

    norm = state.get("normalized_contact") or {}
    rp   = state.get("realtor_profile") or {}
    tier = usage_tracker.resolve_snapshot_tier(rp, norm)
    lane = str(state.get("glyde_lead_lane") or "active").lower()
    if lane == "nurture":
        tier = "lazy"

    meta = acs_state.ensure_metadata(acs)
    ce = meta.setdefault("contactEnrichment", {})
    if isinstance(ce, dict):
        ce["enrichmentTier"] = tier

    workflow_audit.audit_log_node(
        acs, "classify_enrichment_tier", duration_ms=(time.perf_counter() - t0) * 1000, extra={"tier": tier}
    )
    return {"acs": acs, "enrichment_tier": tier}


# Domains treated as personal email providers — too generic to help with employer lookup.
_PERSONAL_EMAIL_DOMAINS: frozenset[str] = frozenset({
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
    "icloud.com", "me.com", "mac.com", "protonmail.com",
    "proton.me", "aol.com", "msn.com", "live.com",
    "ymail.com", "googlemail.com",
})
# Test / placeholder domains — never use for company detection or queries
_TEST_EMAIL_DOMAINS: frozenset[str] = frozenset({
    "example.com", "example.org", "example.net", "test.com",
    "localhost", "acs-test.dev", "mailinator.com", "yopmail.com",
    "example-acs-test.com", "berkshire-test.com",
})
_HASH_PREFIX_RE = re.compile(r"^[0-9a-f]{8,}\.", re.IGNORECASE)


def _extract_business_email(emails: list) -> tuple[str, str, str]:
    """
    Return (email, local_part, domain) for the first business email found.
    Skips personal providers, test domains, and hash-prefixed locals.
    Returns ("", "", "") when none qualify.
    """
    skip = _PERSONAL_EMAIL_DOMAINS | _TEST_EMAIL_DOMAINS
    for _e in emails:
        if not isinstance(_e, str) or not _e.strip():
            continue
        _local, _, _domain = _e.strip().partition("@")
        _domain = _domain.lower().strip()
        if not _domain or _domain in skip:
            continue
        if _HASH_PREFIX_RE.match(_local):
            continue
        return _e.strip(), _local, _domain
    return "", "", ""


def _company_name_from_domain(domain: str) -> str:
    """
    Convert a domain to a readable company name.
    "techstartup.com" → "Techstartup"
    "berkshire-hathaway.com" → "Berkshire Hathaway"
    """
    base = domain.split(".")[0]
    return base.replace("-", " ").replace("_", " ").title()


def _cap_sources_for_meta(sources: Any, *, max_items: int = 25) -> list[dict[str, str]]:
    """Trim sources for workflow metadata / Automation Lab (bounded size)."""
    if not isinstance(sources, list):
        return []
    out: list[dict[str, str]] = []
    for item in sources[:max_items]:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "title": str(item.get("title") or "")[:500],
                "url": str(item.get("url") or "")[:2000],
                "snippet": str(item.get("snippet") or "")[:4000],
            }
        )
    return out


def _node_web_research(state: EnrichmentState) -> dict[str, Any]:
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    if state.get("failed") or state.get("halt_duplicate"):
        return {"acs": acs}

    norm         = state.get("normalized_contact") or {}
    display_name = (norm.get("display_name") or "").strip()
    emails       = norm.get("emails") if isinstance(norm.get("emails"), list) else []
    uid          = _uid(acs) or ""
    realtor_prof = state.get("realtor_profile") or {}

    # ── Extract business email for company intelligence ───────────────────────
    biz_email, _biz_local, biz_domain = _extract_business_email(emails)
    company_name = _company_name_from_domain(biz_domain) if biz_domain else ""

    # ── Build buyer-focused search query ─────────────────────────────────────
    # Contacts are BUYERS / SELLERS / INVESTORS, not realtors.
    # "real estate" qualifier is intentionally omitted — it finds agents, not clients.
    # If we have a business email: "Name Company" gives targeted professional results.
    # If name only: plain "Name" is sufficient.
    if display_name and company_name:
        query = f"{display_name} {company_name}"
    elif display_name:
        query = display_name
    else:
        query = f"id={norm.get('external_person_id') or 'unknown'}"

    # ── Company homepage as seed URL ─────────────────────────────────────────
    # Direct company-domain scrape bypasses the search engine entirely:
    # one targeted request, zero cost, maximum relevance for employer context.
    seed_urls: list[str] = []
    if biz_domain:
        seed_urls = [f"https://{biz_domain}"]

    enrichment_tier = (state.get("enrichment_tier") or "full").strip().lower()
    lazy = enrichment_tier == "lazy"

    # ── Budget-aware backend selection ────────────────────────────────────────
    mode, budget_usd, spent_usd, premium_backend = usage_tracker.check_mode(
        uid, realtor_profile=realtor_prof
    )
    # Lazy tier never uses paid search; standard budget mode also forces DDG.
    if lazy or mode != "premium":
        force_backend = "duckduckgo"
    else:
        force_backend = None

    # ── Run pipeline ──────────────────────────────────────────────────────────
    wr_limit: int | None = None
    raw_lim = (os.environ.get("ACS_WEB_RESEARCH_RESULT_LIMIT") or "").strip()
    if raw_lim:
        try:
            wr_limit = int(raw_lim)
        except ValueError:
            pass
    if lazy:
        base_lim = wr_limit if wr_limit is not None else 2
        wr_limit = max(1, min(base_lim, 2))

    res, st = web_research_internal.research_query_to_summary(
        query,
        result_limit=wr_limit,
        seed_urls=seed_urls,
        force_backend=force_backend,
        lazy=lazy,
    )
    for _ in range(max(1, int(res.get("llm_calls") or 1))):
        workflow_audit.audit_bump_llm(acs)

    # ── Accumulate token estimate for usage recording ─────────────────────────
    tok_in  = int(res.get("tokens_in") or 0)
    tok_out = int(res.get("tokens_out") or 0)
    tok_est = state.get("token_estimate") or {"in": 0, "out": 0, "search_calls": 0}
    tok_est = {
        "in":           tok_est.get("in", 0) + tok_in,
        "out":          tok_est.get("out", 0) + tok_out,
        "search_calls": tok_est.get("search_calls", 0) + int(res.get("search_calls") or 0),
    }

    meta = acs_state.ensure_metadata(acs)
    ce   = meta.setdefault("contactEnrichment", {})
    summary_text = str(res.get("summary") or "").strip()
    sources_meta = _cap_sources_for_meta(res.get("sources"))
    if isinstance(ce, dict):
        ce["webResearch"] = {
            "http_status":   st,
            "mode":          res.get("mode"),
            "query":         query,
            "company_domain": biz_domain or None,
            "seed_injected": bool(seed_urls),
            "sources_count": len(res.get("sources") or []),
            "summary":       summary_text[:12000],
            "sources":       sources_meta,
            "pipeline":      res.get("pipeline"),
            "budget_mode":   mode,
            "spent_usd":     round(spent_usd, 4),
            "budget_usd":    round(budget_usd, 2),
            "enrichment_tier": enrichment_tier,
        }

    if st >= 400:
        acs_state.append_error(acs, f"web_research failed: {st}")
        acs_state.set_core_meta(acs, {"workflow_id": _WORKFLOW_ID, "status": "failed", "phase": "web_research"})
        workflow_audit.audit_log_node(acs, "web_research", duration_ms=(time.perf_counter() - t0) * 1000, extra={"http": st})
        return {"acs": acs, "failed": True, "research": res, "budget_mode": mode, "token_estimate": tok_est}

    workflow_audit.audit_log_node(
        acs,
        "web_research",
        duration_ms=(time.perf_counter() - t0) * 1000,
        extra={
            "http": st,
            "sources": len(res.get("sources") or []),
            "budget_mode": mode,
            "enrichment_tier": enrichment_tier,
            "company_domain": biz_domain or None,
            "seed_injected": bool(seed_urls),
        },
    )
    return {"acs": acs, "research": res, "budget_mode": mode, "token_estimate": tok_est}


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
        "the updates object MUST include a non-empty suggested_note string (at least two sentences). "
        "This contact is a potential home BUYER, SELLER, or INVESTOR — NOT a real estate agent. "
        "Write a practical CRM note a realtor would find useful before meeting this client. Cover: "
        "(1) Professional background — employer (infer from email domain if research is sparse), role/title, "
        "industry; do NOT call them a realtor or broker unless clearly confirmed in research. "
        "(2) Financial signals — business owner, senior/executive title, high-income profession, "
        "any investor activity visible in research. "
        "(3) Possible motivation for moving — new job, relocation, life event (marriage, growing family, "
        "empty nest, retirement), or any signals from research. "
        "(4) Notable public mentions or community ties. "
        "If research_summary is empty, still write a note using the email domain as employer context. "
        "Keep the note concise (under 400 words), factual, and free of speculation beyond what is "
        "supported by the data."
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
    parsed_root: dict[str, Any] | None = None
    try:
        parsed = json.loads(raw) if raw.strip() else {}
        if isinstance(parsed, dict):
            parsed_root = parsed
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

    # Accumulate token estimate
    tok_in_synth  = len(json.dumps(messages)) // 4
    tok_out_synth = len(raw) // 4
    prior_tok = state.get("token_estimate") or {"in": 0, "out": 0, "search_calls": 0}
    token_estimate = {
        "in":           prior_tok.get("in", 0) + tok_in_synth,
        "out":          prior_tok.get("out", 0) + tok_out_synth,
        "search_calls": prior_tok.get("search_calls", 0),
    }

    syn_conf: str | None = None
    syn_rat: str | None = None
    if isinstance(parsed_root, dict):
        _c = parsed_root.get("confidence")
        _r = parsed_root.get("rationale")
        if isinstance(_c, str) and _c.strip():
            syn_conf = _c.strip()[:500]
        if isinstance(_r, str) and _r.strip():
            syn_rat = _r.strip()[:8000]

    meta = acs_state.ensure_metadata(acs)
    ce = meta.setdefault("contactEnrichment", {})
    if isinstance(ce, dict):
        syn_meta: dict[str, Any] = {
            "http_status": st,
            "keys": list(updates.keys()),
            "coercion": coercion,
            "fallback_note": used_fallback,
        }
        if syn_conf:
            syn_meta["confidence"] = syn_conf
        if syn_rat:
            syn_meta["rationale"] = syn_rat
        ce["synthesis"] = syn_meta

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
    return {"acs": acs, "synthesis_updates": updates, "token_estimate": token_estimate}


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


def _node_persist_intel_snapshot(state: EnrichmentState) -> dict[str, Any]:
    """Store last-known contact fingerprint + research summary for delta workflows."""
    acs: dict = state["acs"]
    if state.get("failed") or state.get("halt_duplicate"):
        return {"acs": acs}

    uid = _uid(acs)
    norm = state.get("normalized_contact") or {}
    research = state.get("research") or {}
    if not uid or not isinstance(norm.get("person_id"), int) or norm["person_id"] <= 0:
        return {"acs": acs}

    doc_id = normalize_integration_payload.internal_client_doc_id(norm)
    path = f"Realtors/{uid}/InternalClients/{doc_id}"
    tier = (state.get("enrichment_tier") or "full").strip().lower()
    acs_intel = {
        "snapshot": {
            "display_name": norm.get("display_name"),
            "emails":       norm.get("emails"),
            "phones":       norm.get("phones"),
            "person_id":    norm.get("person_id"),
        },
        "lastWebSummary":     (research.get("summary") or "")[:4000],
        "lastEnrichmentTier": tier,
        "lastEnrichedAt":     datetime.now(timezone.utc).isoformat(),
    }
    payload = {"ownerUid": uid, "createdBy": uid, "acsIntel": acs_intel}
    try:
        _, pst = db_internal.upsert_merge(path, payload, acting_uid=uid, timeout=15)
        if pst not in (200, 201):
            _logger.warning("persist_intel_snapshot: upsert http=%s path=%s", pst, path)
    except Exception:
        _logger.warning("persist_intel_snapshot: failed for %s", path, exc_info=True)

    return {"acs": acs}


def _node_record_usage(state: EnrichmentState) -> dict[str, Any]:
    """
    Best-effort usage recording.  Runs after finalize so it never blocks enrichment.
    Skipped for duplicate-halted runs (no LLM was called).
    """
    acs: dict = state["acs"]
    if state.get("halt_duplicate") or state.get("failed"):
        return {"acs": acs}

    uid = _uid(acs)
    if not uid:
        return {"acs": acs}

    tok    = state.get("token_estimate") or {}
    mode   = state.get("budget_mode") or "premium"
    meta   = acs_state.ensure_metadata(acs)
    ce     = meta.get("contactEnrichment") or {}
    wr     = ce.get("webResearch") or {}
    pipe   = wr.get("pipeline") or {}
    be     = pipe.get("search_backend") or "duckduckgo"

    budget_usd, _ = usage_tracker.get_budget_config(uid, state.get("realtor_profile"))
    etier = (state.get("enrichment_tier") or "full").strip().lower()
    usage_tier = "lazy_snapshot" if etier == "lazy" else "full_snapshot"
    raw_cost = usage_tracker.record_workflow_run(
        uid,
        workflow_id="contact.enrichment_v1",
        usage_tier=usage_tier,
        mode=mode,
        search_backend=be,
        tokens_in=int(tok.get("in") or 0),
        tokens_out=int(tok.get("out") or 0),
        search_calls=int(tok.get("search_calls") or 0),
        budget_usd=budget_usd,
    )

    if isinstance(ce, dict):
        ce["usageRecorded"] = {
            "raw_cost_usd": round(raw_cost, 6),
            "budget_mode": mode,
            "usage_tier": usage_tier,
            "enrichment_tier": etier,
        }
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
    g.add_node("load_glyde_lead_lane", _node_load_glyde_lead_lane)
    g.add_node("classify_enrichment_tier", _node_classify_enrichment_tier)
    g.add_node("web_research", _node_web_research)
    g.add_node("synthesis", _node_synthesis)
    g.add_node("policy_screen", _node_policy_screen)
    g.add_node("map_provider", _node_map_provider)
    g.add_node("send_provider", _node_send_provider)
    g.add_node("persist_intel_snapshot", _node_persist_intel_snapshot)
    g.add_node("record_usage", _node_record_usage)
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
    g.add_edge("normalize", "load_glyde_lead_lane")
    g.add_edge("load_glyde_lead_lane", "classify_enrichment_tier")
    g.add_edge("classify_enrichment_tier", "web_research")
    g.add_edge("web_research", "synthesis")
    g.add_edge("synthesis", "policy_screen")
    g.add_edge("policy_screen", "map_provider")
    g.add_edge("map_provider", "send_provider")
    g.add_edge("send_provider", "persist_intel_snapshot")
    g.add_edge("persist_intel_snapshot", "record_usage")
    g.add_edge("record_usage", "finalize")
    g.add_edge("duplicate_finale", END)
    g.add_edge("finalize", END)
    return g.compile()

"""ads.management_v1 — create, update, or delete ad campaigns on Google Ads + Meta.

Flow:
  load_ad_request → validate_urls → llm_generate_copy → store_pending_record
  → dispatch_to_ad_providers → store_results → finalize

volatile_external: True — calls Google Ads and Meta Ads APIs via outbound actions.

The integration service handles actual ad platform API calls through the
``apply_ads_outbound`` tool/action. Core assembles the request and records intent.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import time
import uuid
from typing import Any, Literal, TypedDict
from urllib.parse import urlparse

from langgraph.graph import END, StateGraph

from clients import db_internal, llm_internal
from state import acs_state
from state.execution_policy import volatile_external_allowed
from workflows import workflow_audit

_logger = logging.getLogger(__name__)

_WORKFLOW_ID = "ads.management_v1"

AD_ACTIONS = frozenset({"create", "update", "pause", "delete"})


class AdsManagementState(TypedDict, total=False):
    acs: dict[str, Any]
    failed: bool
    realtor_profile: dict[str, Any]
    glyde_settings: dict[str, Any]
    ad_request: dict[str, Any]
    validated_urls: list[str]
    ad_copy: dict[str, Any]
    campaign_record_id: str


def _uid(acs: dict) -> str | None:
    u = acs.get("user_id")
    return u.strip() if isinstance(u, str) and u.strip() else None


def _iso_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _node_load_ad_request(state: AdsManagementState) -> dict[str, Any]:
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    workflow_audit.audit_run_start(acs, _WORKFLOW_ID)

    uid = _uid(acs)
    if not uid:
        acs_state.append_error(acs, "user_id missing")
        acs_state.set_core_meta(acs, {"workflow_id": _WORKFLOW_ID, "status": "failed", "phase": "load_request"})
        return {"acs": acs, "failed": True}

    profile_body, _ = db_internal.read_document(f"Realtors/{uid}", acting_uid=uid)
    workflow_audit.audit_bump_db_read(acs)
    profile = profile_body.get("data") if isinstance(profile_body.get("data"), dict) else {}

    settings_body, _ = db_internal.read_document(f"Realtors/{uid}/GlydeSettings/config", acting_uid=uid)
    workflow_audit.audit_bump_db_read(acs)
    settings = settings_body.get("data") if isinstance(settings_body.get("data"), dict) else {}

    payload = acs.get("payload") if isinstance(acs.get("payload"), dict) else {}
    ad_req = payload.get("adRequest") if isinstance(payload.get("adRequest"), dict) else payload

    action = str(ad_req.get("action") or "create").lower()
    if action not in AD_ACTIONS:
        acs_state.append_error(acs, f"invalid action '{action}'; must be one of {sorted(AD_ACTIONS)}")
        acs_state.set_core_meta(acs, {"workflow_id": _WORKFLOW_ID, "status": "failed", "phase": "load_request"})
        return {"acs": acs, "failed": True}

    workflow_audit.audit_log_node(acs, "load_ad_request", duration_ms=(time.perf_counter() - t0) * 1000, extra={"action": action})
    return {"acs": acs, "failed": False, "realtor_profile": profile, "glyde_settings": settings, "ad_request": ad_req}


def _node_validate_urls(state: AdsManagementState) -> dict[str, Any]:
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    if state.get("failed"):
        return {"acs": acs}

    req = state.get("ad_request") or {}
    action = str(req.get("action") or "create").lower()

    if action == "delete":
        workflow_audit.audit_log_node(acs, "validate_urls", duration_ms=(time.perf_counter() - t0) * 1000, extra={"skipped": "delete_action"})
        return {"acs": acs, "validated_urls": []}

    raw_urls = req.get("urls") or req.get("landingUrls") or []
    if isinstance(raw_urls, str):
        raw_urls = [raw_urls]

    valid: list[str] = []
    invalid: list[str] = []
    for u in raw_urls:
        try:
            parsed = urlparse(str(u).strip())
            if parsed.scheme in ("http", "https") and parsed.netloc:
                valid.append(str(u).strip())
            else:
                invalid.append(str(u))
        except Exception:
            invalid.append(str(u))

    if not valid and action in ("create", "update"):
        acs_state.append_error(acs, f"no valid URLs provided; invalid: {invalid[:5]}")
        acs_state.set_core_meta(acs, {"workflow_id": _WORKFLOW_ID, "status": "failed", "phase": "validate_urls"})
        return {"acs": acs, "failed": True}

    workflow_audit.audit_log_node(acs, "validate_urls", duration_ms=(time.perf_counter() - t0) * 1000, extra={"valid": len(valid), "invalid": len(invalid)})
    return {"acs": acs, "validated_urls": valid}


def _node_llm_generate_copy(state: AdsManagementState) -> dict[str, Any]:
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    if state.get("failed"):
        return {"acs": acs}

    req = state.get("ad_request") or {}
    action = str(req.get("action") or "create").lower()

    if action in ("pause", "delete"):
        workflow_audit.audit_log_node(acs, "llm_generate_copy", duration_ms=(time.perf_counter() - t0) * 1000, extra={"skipped": f"{action}_action"})
        return {"acs": acs, "ad_copy": {}}

    if req.get("headline") and req.get("description"):
        copy: dict[str, Any] = {
            "headline": str(req["headline"])[:30],
            "description": str(req["description"])[:90],
        }
        workflow_audit.audit_log_node(acs, "llm_generate_copy", duration_ms=(time.perf_counter() - t0) * 1000, extra={"source": "provided"})
        return {"acs": acs, "ad_copy": copy}

    realtor = state.get("realtor_profile") or {}
    urls = state.get("validated_urls") or []
    realtor_name = realtor.get("displayName") or realtor.get("email") or "Local Real Estate Expert"

    messages = [
        {
            "role": "user",
            "content": json.dumps(
                {
                    "realtor_name": realtor_name,
                    "landing_urls": urls[:3],
                    "objective": req.get("objective") or "drive traffic to listing/website",
                    "target_audience": req.get("targetAudience") or "home buyers and sellers",
                    "budget_usd": req.get("dailyBudgetUsd"),
                    "instruction": (
                        "Generate compelling ad copy for a real estate agent. "
                        "Return JSON only: "
                        "{\"headline\": <max 30 chars>, \"description\": <max 90 chars>, "
                        "\"call_to_action\": <string>, \"keywords\": [<5-10 strings>]}"
                    ),
                },
                default=str,
            )[:10_000],
        }
    ]

    ad_copy: dict[str, Any] = {}
    try:
        body, st = llm_internal.complete(
            model=(os.environ.get("ACS_ADS_LLM_MODEL") or "openai/gpt-4o-mini").strip(),
            messages=messages,
            response_format="json",
        )
        workflow_audit.audit_bump_llm(acs)
        if st < 400:
            raw = body.get("text") or body.get("json") or ""
            try:
                parsed = json.loads(raw) if isinstance(raw, str) else (raw if isinstance(raw, dict) else {})
                if isinstance(parsed, dict):
                    ad_copy = {
                        "headline": str(parsed.get("headline") or "")[:30],
                        "description": str(parsed.get("description") or "")[:90],
                        "call_to_action": str(parsed.get("call_to_action") or "Learn More")[:20],
                        "keywords": [str(k)[:50] for k in (parsed.get("keywords") or [])[:10]],
                    }
            except (json.JSONDecodeError, TypeError):
                pass
    except Exception as e:
        acs_state.append_error(acs, f"ad copy llm error (non-fatal): {e!s}")

    if not ad_copy.get("headline"):
        ad_copy = {
            "headline": f"{realtor_name[:25]} — Expert",
            "description": "Trusted local real estate agent. Buy or sell with confidence.",
            "call_to_action": "Learn More",
            "keywords": ["real estate", "homes for sale", "realtor"],
        }

    workflow_audit.audit_log_node(acs, "llm_generate_copy", duration_ms=(time.perf_counter() - t0) * 1000, extra={"headline_len": len(ad_copy.get("headline") or "")})
    return {"acs": acs, "ad_copy": ad_copy}


def _node_store_pending_record(state: AdsManagementState) -> dict[str, Any]:
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    if state.get("failed"):
        return {"acs": acs}

    uid = _uid(acs)
    if not uid:
        return {"acs": acs}

    req = state.get("ad_request") or {}
    record_id = str(req.get("campaignId") or uuid.uuid4())
    record: dict[str, Any] = {
        "ownerUid": uid,
        "campaignId": record_id,
        "action": req.get("action") or "create",
        "status": "pending",
        "urls": state.get("validated_urls") or [],
        "adCopy": state.get("ad_copy") or {},
        "platforms": req.get("platforms") or ["google_ads", "meta_ads"],
        "dailyBudgetUsd": req.get("dailyBudgetUsd"),
        "objective": req.get("objective") or "traffic",
        "createdAt": _iso_now(),
        "updatedAt": _iso_now(),
        "workflowId": _WORKFLOW_ID,
    }
    _, st = db_internal.upsert_merge(f"Realtors/{uid}/AdCampaigns/{record_id}", record, acting_uid=uid)

    workflow_audit.audit_log_node(acs, "store_pending_record", duration_ms=(time.perf_counter() - t0) * 1000, extra={"http": st, "id": record_id})
    return {"acs": acs, "campaign_record_id": record_id}


def _node_dispatch_to_ad_providers(state: AdsManagementState) -> dict[str, Any]:
    acs: dict = state["acs"]
    t0 = time.perf_counter()
    if state.get("failed"):
        return {"acs": acs}

    req = state.get("ad_request") or {}
    settings = state.get("glyde_settings") or {}
    record_id = state.get("campaign_record_id") or ""

    if not volatile_external_allowed(acs):
        meta = acs_state.ensure_metadata(acs)
        meta.setdefault("adsManagement", {})
        if isinstance(meta["adsManagement"], dict):
            meta["adsManagement"]["mode"] = "analytical_no_dispatch"
        workflow_audit.audit_log_node(acs, "dispatch_to_ad_providers", duration_ms=(time.perf_counter() - t0) * 1000, extra={"skipped": "volatile_external_not_allowed"})
        return {"acs": acs}

    platforms = req.get("platforms") or ["google_ads", "meta_ads"]
    actions: list[dict[str, Any]] = []

    for platform in platforms:
        actions.append({
            "name": "manageAdCampaign",
            "payload": {
                "platform": platform,
                "action": req.get("action") or "create",
                "campaignId": record_id,
                "urls": state.get("validated_urls") or [],
                "adCopy": state.get("ad_copy") or {},
                "dailyBudgetUsd": req.get("dailyBudgetUsd"),
                "targetAudience": req.get("targetAudience"),
                "googleAdsAccountId": settings.get("googleAdsAccountId"),
                "metaAdsAccountId": settings.get("metaAdsAccountId"),
            },
            "effect": "volatile_external",
        })

    meta = acs_state.ensure_metadata(acs)
    meta["outboundActions"] = actions
    meta.setdefault("adsManagement", {})
    if isinstance(meta["adsManagement"], dict):
        meta["adsManagement"]["actions_queued"] = len(actions)
        meta["adsManagement"]["platforms"] = platforms

    workflow_audit.audit_log_node(acs, "dispatch_to_ad_providers", duration_ms=(time.perf_counter() - t0) * 1000, extra={"actions": len(actions)})
    return {"acs": acs}


def _node_finalize(state: AdsManagementState) -> dict[str, Any]:
    acs: dict = state["acs"]
    if state.get("failed"):
        acs_state.set_core_meta(acs, {"workflow_id": _WORKFLOW_ID, "status": "failed", "phase": "terminal"})
        workflow_audit.audit_run_finish(acs, status="failed")
    else:
        acs_state.set_core_meta(acs, {"workflow_id": _WORKFLOW_ID, "status": "completed", "phase": "done"})
        workflow_audit.audit_log_node(acs, "finalize")
        workflow_audit.audit_run_finish(acs, status="completed")
    return {"acs": acs}


def build_ads_management_graph():
    g = StateGraph(AdsManagementState)
    g.add_node("load_ad_request", _node_load_ad_request)
    g.add_node("validate_urls", _node_validate_urls)
    g.add_node("llm_generate_copy", _node_llm_generate_copy)
    g.add_node("store_pending_record", _node_store_pending_record)
    g.add_node("dispatch_to_ad_providers", _node_dispatch_to_ad_providers)
    g.add_node("finalize", _node_finalize)

    g.set_entry_point("load_ad_request")
    g.add_edge("load_ad_request", "validate_urls")
    g.add_edge("validate_urls", "llm_generate_copy")
    g.add_edge("llm_generate_copy", "store_pending_record")
    g.add_edge("store_pending_record", "dispatch_to_ad_providers")
    g.add_edge("dispatch_to_ad_providers", "finalize")
    g.add_edge("finalize", END)
    return g.compile()

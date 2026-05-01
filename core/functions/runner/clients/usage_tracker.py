"""
Per-user enrichment usage tracking and budget enforcement.

Firestore path (via db_internal gateway):
    Realtors/{uid}/BillingUsage/{YYYY-MM}   — monthly rolling aggregate

Budget config embedded in Realtors/{uid} document (optional fields):
    enrichmentConfig.monthlyBudgetUsd       — default: 1.00
    enrichmentConfig.premiumSearchBackend   — default: ACS_WEB_SEARCH_BACKEND env var

Budget modes
────────────
  "premium"  — use configured premium search backend (Brave if key present, else DDG)
               Company domain seed-URL scraping always runs regardless of mode.
  "standard" — DDG only (free).  LLM synthesis quality is identical.
               Triggered when monthly cost >= monthly budget.

Cost model (USD, approximate — used for quota, not invoicing)
─────────────────────────────────────────────────────────────
  gpt-4o-mini via OpenRouter:
    Input:  $0.15 / 1M tokens
    Output: $0.60 / 1M tokens
  Brave Search API:
    Free tier: 2 000 calls/month, then $5 / 1 000 calls = $0.005/call
  DuckDuckGo HTML scraping:
    $0.00 (free, no official API)

Typical enrichment cost:
  Premium (Brave):  ~7 000 in + ~1 200 out tokens + 1 Brave call
                    ≈ $0.00105 + $0.00072 + $0.005 ≈ $0.007 / enrichment
  Standard (DDG):   ~7 000 in + ~1 200 out tokens
                    ≈ $0.00105 + $0.00072         ≈ $0.002 / enrichment

With $1.00 / month budget:
  Premium:  ~143 enrichments before quota → standard fallback
  Standard: ~500 enrichments (essentially unlimited for most teams)

Usage is tracked per-user per-month in Firestore with a shallow read-modify-write.
Concurrent enrichments (rare for typical realtor workloads) may slightly over- or
under-count, which is acceptable given the tiny per-call amounts.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Literal

from clients import db_internal

_logger = logging.getLogger(__name__)

SnapshotTier = Literal["lazy", "full"]

# Same personal-email notion as contact_enrichment_v1 (keep in sync for tier gating).
_PERSONAL_EMAIL_DOMAINS: frozenset[str] = frozenset({
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
    "icloud.com", "me.com", "mac.com", "protonmail.com",
    "proton.me", "aol.com", "msn.com", "live.com",
    "ymail.com", "googlemail.com",
})
_TEST_EMAIL_DOMAINS: frozenset[str] = frozenset({
    "example.com", "example.org", "example.net", "test.com",
    "localhost", "acs-test.dev", "mailinator.com", "yopmail.com",
    "example-acs-test.com", "berkshire-test.com",
})

# ── Cost model ────────────────────────────────────────────────────────────────

_LLM_INPUT_COST_PER_1M  = 0.15    # gpt-4o-mini input tokens
_LLM_OUTPUT_COST_PER_1M = 0.60    # gpt-4o-mini output tokens
_BRAVE_COST_PER_CALL    = 0.005   # Brave paid tier (after 2 000 free/month)
_DDG_COST_PER_CALL      = 0.0     # DuckDuckGo HTML — free

DEFAULT_MONTHLY_BUDGET_USD  = 1.00
DEFAULT_PREMIUM_BACKEND     = "duckduckgo"   # overridden by ACS_WEB_SEARCH_BACKEND

# ── Helpers ───────────────────────────────────────────────────────────────────

def _current_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _estimate_search_cost(backend: str, calls: int) -> float:
    """Estimate USD cost for `calls` search API requests using `backend`."""
    if backend in ("brave",):
        return _BRAVE_COST_PER_CALL * calls
    return _DDG_COST_PER_CALL * calls


def _estimate_llm_cost(tokens_in: int, tokens_out: int) -> float:
    return (tokens_in / 1_000_000) * _LLM_INPUT_COST_PER_1M + \
           (tokens_out / 1_000_000) * _LLM_OUTPUT_COST_PER_1M


# ── Public API ────────────────────────────────────────────────────────────────

def _norm_has_business_email(norm: dict[str, Any] | None) -> bool:
    """True if normalized contact has a non-consumer email domain."""
    if not isinstance(norm, dict):
        return False
    emails = norm.get("emails")
    if not isinstance(emails, list):
        return False
    skip = _PERSONAL_EMAIL_DOMAINS | _TEST_EMAIL_DOMAINS
    for e in emails:
        if not isinstance(e, str) or "@" not in e:
            continue
        _, _, dom = e.strip().partition("@")
        dom = dom.lower().strip()
        if dom and dom not in skip:
            return True
    return False


def resolve_snapshot_tier(
    realtor_profile: dict[str, Any] | None,
    normalized_contact: dict[str, Any] | None,
) -> SnapshotTier:
    """
    Decide lazy vs full enrichment for ``peopleCreated``.

    Config on ``Realtors/{uid}.enrichmentConfig``:

    - ``lazyDefaultOnCreate`` (bool, default True) — when True, new contacts use the
      cheaper lazy path unless a full trigger matches.
    - ``fullOnBusinessEmail`` (bool, default True) — business (non-consumer) email → full.

    When ``lazyDefaultOnCreate`` is False, always ``full`` (legacy behaviour).
    """
    cfg: dict[str, Any] = {}
    if isinstance(realtor_profile, dict):
        raw = realtor_profile.get("enrichmentConfig")
        if isinstance(raw, dict):
            cfg = raw

    if cfg.get("lazyDefaultOnCreate") is False:
        return "full"

    if cfg.get("fullOnBusinessEmail", True) and _norm_has_business_email(normalized_contact):
        return "full"

    return "lazy"


def get_budget_config(uid: str, realtor_profile: dict[str, Any] | None = None) -> tuple[float, str]:
    """
    Return (monthly_budget_usd, premium_backend) for this user.

    Reads from realtor_profile["enrichmentConfig"] if present, otherwise uses
    environment defaults.  Never raises.
    """
    budget_usd       = DEFAULT_MONTHLY_BUDGET_USD
    premium_backend  = (
        os.environ.get("ACS_WEB_SEARCH_BACKEND") or DEFAULT_PREMIUM_BACKEND
    ).strip().lower() or DEFAULT_PREMIUM_BACKEND

    if isinstance(realtor_profile, dict):
        cfg = realtor_profile.get("enrichmentConfig")
        if isinstance(cfg, dict):
            try:
                raw_budget = cfg.get("monthlyBudgetUsd")
                if raw_budget is not None:
                    budget_usd = max(0.0, float(raw_budget))
            except (TypeError, ValueError):
                pass
            raw_backend = cfg.get("premiumSearchBackend")
            if isinstance(raw_backend, str) and raw_backend.strip():
                premium_backend = raw_backend.strip().lower()

    return budget_usd, premium_backend


def get_monthly_usage(uid: str) -> dict[str, Any]:
    """
    Return the current-month usage document for `uid`.
    Returns {} on any error (treated as zero usage).
    """
    month = _current_month()
    path  = f"Realtors/{uid}/BillingUsage/{month}"
    try:
        body, st = db_internal.read_document(path, acting_uid=uid)
        if st == 200 and isinstance(body.get("data"), dict):
            return body["data"]
    except Exception:
        _logger.debug("usage_tracker: get_monthly_usage failed for uid=%s", uid, exc_info=True)
    return {}


def check_mode(
    uid: str,
    realtor_profile: dict[str, Any] | None = None,
) -> tuple[str, float, float, str]:
    """
    Return (mode, budget_usd, spent_usd, premium_backend).

    mode is "premium" when spent_usd < budget_usd, "standard" otherwise.
    Never raises — on any error returns ("premium", default_budget, 0.0, default_backend)
    so that a DB hiccup does not silently degrade quality.
    """
    budget_usd, premium_backend = get_budget_config(uid, realtor_profile)
    try:
        usage = get_monthly_usage(uid)
        spent_usd = float(usage.get("spentUsd") or 0.0)
    except Exception:
        spent_usd = 0.0

    mode = "standard" if spent_usd >= budget_usd else "premium"
    return mode, budget_usd, spent_usd, premium_backend


def _cost_weight_for_tier(usage_tier: str) -> float:
    if usage_tier == "lazy_snapshot":
        return 0.25
    if usage_tier == "intel_delta":
        return 0.20
    return 1.0


def record_workflow_run(
    uid: str,
    *,
    workflow_id: str,
    usage_tier: str,
    mode: str,
    search_backend: str,
    tokens_in: int,
    tokens_out: int,
    search_calls: int,
    budget_usd: float,
    cost_weight: float | None = None,
) -> float:
    """
    Record one workflow run against the monthly budget.

    ``usage_tier``: ``lazy_snapshot`` | ``full_snapshot`` | ``intel_delta``

    ``cost_weight`` scales how much of the estimated USD counts toward ``spentUsd``
    (defaults from tier: lazy 0.25×, delta 0.20×, full 1.0×).

    Returns raw (unweighted) estimated USD for this run's LLM + search components.
    """
    month = _current_month()
    path  = f"Realtors/{uid}/BillingUsage/{month}"

    w = cost_weight if cost_weight is not None else _cost_weight_for_tier(usage_tier)

    llm_cost    = _estimate_llm_cost(tokens_in, tokens_out)
    search_cost = _estimate_search_cost(search_backend, search_calls)
    raw_total   = llm_cost + search_cost
    weighted    = raw_total * w

    current: dict[str, Any] = {}
    try:
        body, st = db_internal.read_document(path, acting_uid=uid)
        if st == 200 and isinstance(body.get("data"), dict):
            current = body["data"]
    except Exception:
        pass

    is_premium = mode == "premium"
    wf_counts = dict(current.get("workflowRunCounts") or {})
    wf_counts[workflow_id] = int(wf_counts.get(workflow_id) or 0) + 1

    lazy_n   = int(current.get("lazySnapshotRuns") or 0)
    full_n   = int(current.get("fullSnapshotRuns") or 0)
    delta_n  = int(current.get("intelDeltaRuns") or 0)
    if usage_tier == "lazy_snapshot":
        lazy_n += 1
    elif usage_tier == "intel_delta":
        delta_n += 1
    else:
        full_n += 1

    updated: dict[str, Any] = {
        "ownerUid":                    uid,
        "month":                       month,
        "budgetUsd":                   budget_usd,
        "spentUsd":                    round(float(current.get("spentUsd") or 0) + weighted, 6),
        "enrichmentsTotal":            int(current.get("enrichmentsTotal") or 0) + 1,
        "enrichmentsPremium":          int(current.get("enrichmentsPremium") or 0) + (1 if is_premium else 0),
        "enrichmentsStandard":         int(current.get("enrichmentsStandard") or 0) + (0 if is_premium else 1),
        "llmTokensInEstimated":        int(current.get("llmTokensInEstimated") or 0) + tokens_in,
        "llmTokensOutEstimated":       int(current.get("llmTokensOutEstimated") or 0) + tokens_out,
        "llmCostUsd":                  round(float(current.get("llmCostUsd") or 0) + llm_cost * w, 6),
        "searchApiCalls":              int(current.get("searchApiCalls") or 0) + search_calls,
        "searchCostUsd":               round(float(current.get("searchCostUsd") or 0) + search_cost * w, 6),
        "lastWorkflowId":             workflow_id,
        "lastUsageTier":              usage_tier,
        "lastUpdatedSearch":           search_backend,
        "lastUpdated":                 datetime.now(timezone.utc).isoformat(),
        "workflowRunCounts":          wf_counts,
        "lazySnapshotRuns":           lazy_n,
        "fullSnapshotRuns":           full_n,
        "intelDeltaRuns":             delta_n,
    }

    try:
        _, st = db_internal.upsert_merge(path, updated, acting_uid=uid, timeout=10)
        if st not in (200, 201):
            _logger.warning("usage_tracker: upsert returned %s for uid=%s", st, uid)
    except Exception:
        _logger.warning("usage_tracker: record_workflow_run failed for uid=%s", uid, exc_info=True)

    return raw_total


def record_enrichment(
    uid: str,
    *,
    mode: str,
    search_backend: str,
    tokens_in: int,
    tokens_out: int,
    search_calls: int,
    budget_usd: float,
) -> float:
    """Deprecated: use ``record_workflow_run``. Kept for backward compatibility."""
    return record_workflow_run(
        uid,
        workflow_id="contact.enrichment_v1",
        usage_tier="full_snapshot",
        mode=mode,
        search_backend=search_backend,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        search_calls=search_calls,
        budget_usd=budget_usd,
        cost_weight=1.0,
    )


def usage_summary(uid: str, realtor_profile: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Return a caller-facing usage summary for the current month.
    Safe to expose via API — contains no secrets.
    """
    budget_usd, premium_backend = get_budget_config(uid, realtor_profile)
    usage = get_monthly_usage(uid)
    spent = float(usage.get("spentUsd") or 0.0)
    remaining = max(0.0, budget_usd - spent)
    pct = round((spent / budget_usd * 100), 1) if budget_usd > 0 else 0.0
    mode = "standard" if spent >= budget_usd else "premium"

    return {
        "month":                     _current_month(),
        "budget_usd":                round(budget_usd, 2),
        "spent_usd":                 round(spent, 4),
        "remaining_usd":             round(remaining, 4),
        "budget_used_pct":           pct,
        "mode":                      mode,
        "premium_backend":           premium_backend,
        "enrichments_total":         int(usage.get("enrichmentsTotal") or 0),
        "enrichments_premium":       int(usage.get("enrichmentsPremium") or 0),
        "enrichments_standard":      int(usage.get("enrichmentsStandard") or 0),
        "lazy_snapshot_runs":      int(usage.get("lazySnapshotRuns") or 0),
        "full_snapshot_runs":      int(usage.get("fullSnapshotRuns") or 0),
        "intel_delta_runs":        int(usage.get("intelDeltaRuns") or 0),
        "workflow_run_counts":     dict(usage.get("workflowRunCounts") or {}),
        "llm_tokens_in_estimated":   int(usage.get("llmTokensInEstimated") or 0),
        "llm_tokens_out_estimated":  int(usage.get("llmTokensOutEstimated") or 0),
        "breakdown": {
            "llm_cost_usd":          round(float(usage.get("llmCostUsd") or 0), 4),
            "search_cost_usd":       round(float(usage.get("searchCostUsd") or 0), 4),
            "search_api_calls":      int(usage.get("searchApiCalls") or 0),
        },
    }

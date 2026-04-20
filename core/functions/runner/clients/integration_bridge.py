"""Call integration-bridge internal workers from core-run (platform OIDC)."""

from __future__ import annotations

import os
from typing import Any

from clients import gcp_identity
from clients.http_exec import post_json_with_bearer


def fub_refresh_and_sync_webhooks(uid: str, *, refresh_tokens_first: bool = True) -> tuple[dict[str, Any], int]:
    """
    Synchronously refresh FUB OAuth tokens (optional) and reconcile all webhooks for ``uid``.

    Requires ``INTEGRATION_BRIDGE_BASE_URL`` (same value as terraform ``fub_webhook_sync_worker_url``).
    """
    base = (os.environ.get("INTEGRATION_BRIDGE_BASE_URL") or "").strip().rstrip("/")
    if not base:
        return {"error": "integration_bridge_not_configured", "todo": "Set INTEGRATION_BRIDGE_BASE_URL on core-run"}, 503

    token = gcp_identity.id_token_for_integration_bridge()
    url = f"{base}/integrations/followupboss/internal/webhook_sync"
    payload: dict[str, Any] = {
        "uid": uid.strip(),
        "refreshTokensFirst": refresh_tokens_first,
    }
    return post_json_with_bearer(url, payload, bearer=token, timeout=120)


def from_providers(uid: str, provider_states: list) -> tuple[dict[str, Any], int]:
    """
    Expand ``provider_states`` into an ``acs_patch`` via integration (platform OIDC).

    Used by core workflows before internal normalization when the caller passes
    ``payload.providerLoad`` instead of pre-built ``source_batches``.
    """
    base = (os.environ.get("INTEGRATION_BRIDGE_BASE_URL") or "").strip().rstrip("/")
    if not base:
        return {"error": "integration_bridge_not_configured", "todo": "Set INTEGRATION_BRIDGE_BASE_URL on core-run"}, 503

    token = gcp_identity.id_token_for_integration_bridge()
    url = f"{base}/integrations/internal/state/from_providers"
    payload: dict[str, Any] = {
        "uid": uid.strip(),
        "provider_states": provider_states if isinstance(provider_states, list) else [],
    }
    return post_json_with_bearer(url, payload, bearer=token, timeout=120)


def to_providers(uid: str, acs_state: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """
    Project ACS into provider-shaped blocks (summaries, outbound echoes) for clients / BFF.
    """
    base = (os.environ.get("INTEGRATION_BRIDGE_BASE_URL") or "").strip().rstrip("/")
    if not base:
        return {"provider_states": [], "skipped": True, "reason": "integration_bridge_not_configured"}, 200

    token = gcp_identity.id_token_for_integration_bridge()
    url = f"{base}/integrations/internal/state/to_providers"
    payload: dict[str, Any] = {"uid": uid.strip(), "acs_state": acs_state}
    return post_json_with_bearer(url, payload, bearer=token, timeout=60)


def apply_followupboss_outbound(uid: str, actions: list) -> tuple[dict[str, Any], int]:
    """
    Best-effort synchronous CRM apply via integration-bridge.

    When ``INTEGRATION_BRIDGE_BASE_URL`` is unset or the worker URL is not deployed, returns
    ``{ok: true, mode: "deferred"}`` so callers can rely on the integration webhook path to apply
    ``metadata.outboundActions`` after core returns.
    """
    base = (os.environ.get("INTEGRATION_BRIDGE_BASE_URL") or "").strip().rstrip("/")
    if not base:
        return {"ok": True, "mode": "deferred", "reason": "integration_bridge_not_configured"}, 200

    token = gcp_identity.id_token_for_integration_bridge()
    url = f"{base}/integrations/followupboss/internal/outbound_apply"
    payload: dict[str, Any] = {"uid": uid.strip(), "actions": actions}
    return post_json_with_bearer(url, payload, bearer=token, timeout=120)

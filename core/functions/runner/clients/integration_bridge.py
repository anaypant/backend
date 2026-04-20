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

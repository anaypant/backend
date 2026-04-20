"""Minimal OIDC helpers (mirror integration store/gcp_identity)."""

from __future__ import annotations

import os

from google.auth.transport.requests import Request
from google.oauth2 import id_token as oauth_id_token


def normalize_internal_gateway_hostname(raw: str) -> str:
    h = (raw or "").strip()
    while h:
        low = h.lower()
        if low.startswith("https://"):
            h = h[8:].strip()
        elif low.startswith("http://"):
            h = h[7:].strip()
        else:
            break
    if "/" in h:
        h = h.split("/", 1)[0].strip()
    if h.endswith(":443"):
        h = h[:-4].strip()
    return h.rstrip("/").strip()


def id_token_for_db_gateway() -> str:
    host = normalize_internal_gateway_hostname(os.environ.get("DB_INTERNAL_GATEWAY_HOSTNAME") or "")
    if not host:
        raise RuntimeError("DB_INTERNAL_GATEWAY_HOSTNAME is not set")
    audience = f"https://{host}"
    return oauth_id_token.fetch_id_token(Request(), audience)


def id_token_for_llm_gateway() -> str:
    aud = (os.environ.get("LLM_INTERNAL_JWT_AUDIENCE") or "").strip().rstrip("/")
    if not aud:
        raise RuntimeError("LLM_INTERNAL_JWT_AUDIENCE is not set")
    return oauth_id_token.fetch_id_token(Request(), aud)


def id_token_for_integration_bridge() -> str:
    """
    OIDC for POST integration-bridge ``/integrations/followupboss/internal/webhook_sync``
    (same audience as Cloud Tasks: typically the bridge HTTPS origin, no trailing slash).
    """
    base = (os.environ.get("INTEGRATION_BRIDGE_BASE_URL") or "").strip().rstrip("/")
    if not base:
        raise RuntimeError("INTEGRATION_BRIDGE_BASE_URL is not set")
    aud = (os.environ.get("INTEGRATION_BRIDGE_OIDC_AUDIENCE") or base).strip().rstrip("/")
    return oauth_id_token.fetch_id_token(Request(), aud)

"""Verify HS256 JWT from the public API callback bridge (shared ACS_CALLBACK_BRIDGE_SECRET)."""

import os

import jwt

HEADER = "X-ACS-Callback-Bridge-Token"
AUDIENCE = "acs-oauth-callback"


def bridge_secret_configured() -> bool:
    return bool((os.environ.get("ACS_CALLBACK_BRIDGE_SECRET") or "").strip())


def verify_callback_bridge_token(request) -> dict | None:
    secret = (os.environ.get("ACS_CALLBACK_BRIDGE_SECRET") or "").strip()
    if not secret:
        return None
    raw = (request.headers.get(HEADER) or "").strip()
    if not raw.lower().startswith("bearer "):
        return None
    token = raw[7:].strip()
    try:
        return jwt.decode(token, secret, algorithms=["HS256"], audience=AUDIENCE)
    except jwt.InvalidTokenError:
        return None

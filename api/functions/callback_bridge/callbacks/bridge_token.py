"""HS256 JWT minted at the public callback bridge and verified by integration (shared secret)."""

import os
import time

import jwt

AUDIENCE = "acs-oauth-callback"
HEADER = "X-ACS-Callback-Bridge-Token"


def mint_token(*, uid: str, state: str) -> str:
    secret = (os.environ.get("ACS_CALLBACK_BRIDGE_SECRET") or "").strip()
    if not secret:
        return ""
    now = int(time.time())
    payload = {"sub": uid, "state": state, "aud": AUDIENCE, "iat": now, "exp": now + 300}
    return jwt.encode(payload, secret, algorithm="HS256")

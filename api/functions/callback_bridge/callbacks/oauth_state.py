"""OAuth state parsing — must stay aligned with integration followupboss oauth.py."""

import hashlib
import hmac
import os
import re
import urllib.parse

_STATE_RE = re.compile(r"^[a-zA-Z0-9._-]{8,512}$")


def normalize_oauth_state_param(raw: str | None) -> str:
    s = (raw or "").strip()
    if not s:
        return ""
    return urllib.parse.unquote(s)


def state_parse(state: str) -> tuple[str | None, str | None, bool]:
    if not isinstance(state, str) or not _STATE_RE.match(state):
        return None, None, False
    parts = state.split(".")
    if len(parts) < 2:
        return None, None, False
    uid, nonce = parts[0].strip(), parts[1].strip()
    if not uid or not nonce:
        return None, None, False
    secret = (os.environ.get("ACS_OAUTH_STATE_SECRET") or "").strip()
    if not secret:
        return uid, nonce, True
    if len(parts) != 3:
        return None, None, False
    sig = parts[2]
    expected = hmac.new(secret.encode("utf-8"), f"{uid}.{nonce}".encode("utf-8"), hashlib.sha256).hexdigest()
    return uid, nonce, hmac.compare_digest(sig, expected)

"""Public API: Follow Up Boss OAuth redirect callback — validate state, attach bridge token, forward to integration."""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

from callbacks.bridge_token import HEADER, mint_token
from callbacks.oauth_state import normalize_oauth_state_param, state_parse
from gcp_identity import id_token_for_integration_gateway


def _json(body: dict, status: int):
    return (json.dumps(body), status, {"Content-Type": "application/json"})


def _forward_raw(request, query: str):
    """Development / no bridge secret: transparent proxy with service identity only."""
    host = os.environ.get("INTEGRATION_INTERNAL_GATEWAY_HOSTNAME", "").strip().rstrip("/")
    if not host:
        return _json({"error": "INTEGRATION_INTERNAL_GATEWAY_HOSTNAME not configured"}, 503)
    url = f"https://{host}/integrations/followupboss/oauth/callback?{query}"
    token = id_token_for_integration_gateway()
    req = urllib.request.Request(
        url,
        method="GET",
        headers={"Authorization": f"Bearer {token}"},
    )
    return _exec(req)


def _forward_with_bridge(request, query: str, bridge_jwt: str):
    host = os.environ.get("INTEGRATION_INTERNAL_GATEWAY_HOSTNAME", "").strip().rstrip("/")
    if not host:
        return _json({"error": "INTEGRATION_INTERNAL_GATEWAY_HOSTNAME not configured"}, 503)
    url = f"https://{host}/integrations/followupboss/oauth/callback?{query}"
    id_tok = id_token_for_integration_gateway()
    req = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Authorization": f"Bearer {id_tok}",
            f"{HEADER}": f"Bearer {bridge_jwt}",
        },
    )
    return _exec(req)


def _exec(req: urllib.request.Request):
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
            return (raw, resp.status, {"Content-Type": resp.headers.get("Content-Type") or "application/json"})
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        return (raw, e.code, {"Content-Type": e.headers.get("Content-Type") or "application/json"})


def handle(request):
    if request.method != "GET":
        return _json({"error": "method not allowed"}, 405)

    args = request.args
    state = normalize_oauth_state_param(args.get("state"))
    if not state:
        return _json({"error": "missing state"}, 400)

    uid, nonce, ok = state_parse(state)
    if not uid or not nonce or not ok:
        return _json({"error": "invalid state", "phase": "oauth_state_parse"}, 401)

    qs = getattr(request, "query_string", None)
    if isinstance(qs, bytes):
        q = qs.decode("utf-8", errors="replace")
    elif isinstance(qs, str):
        q = qs
    else:
        q = urllib.parse.urlencode(list(args.items()))
    secret = (os.environ.get("ACS_CALLBACK_BRIDGE_SECRET") or "").strip()
    if not secret:
        return _forward_raw(request, q)

    bridge_jwt = mint_token(uid=uid, state=state)
    if not bridge_jwt:
        return _json({"error": "ACS_CALLBACK_BRIDGE_SECRET not configured"}, 503)
    return _forward_with_bridge(request, q, bridge_jwt)

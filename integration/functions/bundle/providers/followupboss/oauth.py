import hashlib
import hmac
import os
import re
import urllib.parse
import uuid

from providers.followupboss.client import FubClient
from providers.followupboss.constants import ALL_WEBHOOK_EVENTS
from store.authn import resolve_realtor_bearer
from store.common import integration_auth_error_response, json_response, now_epoch, public_integration_base_url
from store.profile_repo import (
    fub_config_from_profile,
    load_fub_profile_by_connection_id,
    load_realtor_profile,
    save_fub_profile,
    save_fub_profile_by_connection_id,
)
from store.secret_repo import get_secret, put_secret


def _put_fub_secret(reference_id: str, value: str) -> tuple[str | None, str | None]:
    """Persist a FUB credential; returns (ref, None) or (None, error_message)."""
    try:
        return put_secret(reference_id, value), None
    except (RuntimeError, ValueError) as e:
        return None, str(e)

import bridge_token

_STATE_RE = re.compile(r"^[a-zA-Z0-9._-]{8,512}$")


def _normalize_oauth_state_param(raw: str | None) -> str:
    """Decode query `state` once; providers sometimes leave percent-encoding in place."""
    s = (raw or "").strip()
    if not s:
        return ""
    return urllib.parse.unquote(s)


def _maybe_return_profile_load_error(existing, status):
    """Tag 401 from internal DB gateway so logs distinguish auth vs realtor profile read."""
    if status in (200, 404):
        return None
    err_status = 502 if status >= 500 else status
    if status == 401:
        if isinstance(existing, dict):
            return json_response({**existing, "phase": "db_read"}, err_status)
        return json_response(
            {"error": "db read unauthorized", "detail": existing, "phase": "db_read"},
            err_status,
        )
    return json_response(existing, err_status)


_FUB_CONNECTED_STATUSES = frozenset(
    {
        "connected",
        "connected_with_webhook_sync_issues",
        "needs_owner_for_webhooks",
    }
)


def _fub_is_integrated(fub: dict) -> bool:
    st = dict(fub.get("connection") or {}).get("status")
    return st in _FUB_CONNECTED_STATUSES


def _state_sign(uid: str, nonce: str) -> str:
    secret = (os.environ.get("ACS_OAUTH_STATE_SECRET") or "").strip()
    if not secret:
        return f"{uid}.{nonce}"
    digest = hmac.new(secret.encode("utf-8"), f"{uid}.{nonce}".encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{uid}.{nonce}.{digest}"


def _state_parse(state: str) -> tuple[str | None, str | None, bool]:
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


def _fub_callback_url(request) -> str:
    return f"{public_integration_base_url(request)}/integrations/followupboss/oauth/callback"


def _resolve_authorize_url(state: str, callback_url: str) -> tuple[str | None, dict | None]:
    base = (os.environ.get("FUB_OAUTH_AUTHORIZE_URL") or "").strip()
    client_id = (os.environ.get("FUB_OAUTH_CLIENT_ID") or "").strip()
    if not base:
        return None, {"error": "oauth_authorize_not_configured", "todo": "Set FUB_OAUTH_AUTHORIZE_URL"}
    # https://docs.followupboss.com/docs/oauth-authentication-and-authorization — response_type=auth_code (not "code")
    params = [
        f"state={urllib.parse.quote(state, safe='')}",
        f"redirect_uri={urllib.parse.quote(callback_url, safe='')}",
    ]
    if client_id:
        params.append(f"client_id={urllib.parse.quote(client_id, safe='')}")
    base_lower = base.lower()
    if "response_type=" not in base_lower:
        params.append("response_type=auth_code")
    if "prompt=" not in base_lower:
        params.append("prompt=login")
    sep = "&" if "?" in base else "?"
    return base + sep + "&".join(params), None


def _ensure_all_webhooks(client: FubClient, connection_id: str, callback_base: str) -> tuple[dict, int]:
    webhook_url = f"{callback_base}/integrations/webhooks/followupboss?connectionId={connection_id}"
    existing, status = client.list_webhooks()
    if status >= 400:
        return {"error": "list_webhooks_failed", "detail": existing}, status

    items = existing if isinstance(existing, list) else existing.get("_embedded", {}).get("webhooks", []) if isinstance(existing, dict) else []
    by_event: dict[str, list[dict]] = {}
    for w in items if isinstance(items, list) else []:
        if not isinstance(w, dict):
            continue
        event = w.get("event")
        if not isinstance(event, str):
            continue
        by_event.setdefault(event, []).append(w)

    created = 0
    kept = 0
    removed = 0
    failures: list[dict] = []

    for event in ALL_WEBHOOK_EVENTS:
        candidates = [w for w in by_event.get(event, []) if w.get("url") == webhook_url]
        if candidates:
            kept += 1
        else:
            body, s = client.create_webhook(event, webhook_url)
            if s >= 400:
                failures.append({"event": event, "status": s, "detail": body})
            else:
                created += 1

        # cleanup extras to stay under 2/event/system ceiling
        all_for_event = by_event.get(event, [])
        extras = []
        matched = 0
        for w in all_for_event:
            if w.get("url") == webhook_url and matched == 0:
                matched += 1
                continue
            wid = w.get("id")
            if wid is not None:
                extras.append(wid)
        for wid in extras:
            _b, s = client.delete_webhook(wid)
            if s < 400:
                removed += 1

    needs_owner = any(f.get("status") in (401, 403) for f in failures)
    return {
        "ok": len(failures) == 0,
        "needsOwner": needs_owner,
        "webhookSyncStatus": "needs_owner" if needs_owner else ("ok" if len(failures) == 0 else "partial_error"),
        "callbackUrl": webhook_url,
        "created": created,
        "kept": kept,
        "removed": removed,
        "failures": failures,
        "totalEvents": len(ALL_WEBHOOK_EVENTS),
    }, 200 if len(failures) == 0 else 207


def oauth_start(request):
    decoded, err, _token = resolve_realtor_bearer(request)
    if err:
        return integration_auth_error_response(err)

    uid = decoded["uid"]
    now = now_epoch()
    callback_url = _fub_callback_url(request)

    existing, status = load_realtor_profile(uid)
    maybe_err = _maybe_return_profile_load_error(existing, status)
    if maybe_err:
        return maybe_err

    fub = fub_config_from_profile(existing) or {}
    if _fub_is_integrated(fub):
        conn = dict(fub.get("connection") or {})
        return json_response(
            {
                "error": "already_connected",
                "phase": "fub_oauth",
                "connectionStatus": conn.get("status"),
                "hint": (
                    "Follow Up Boss is already linked. POST /integrations/followupboss/disconnect to unlink, "
                    "then you may start OAuth again."
                ),
                "disconnectPath": "/integrations/followupboss/disconnect",
                "statusPath": "/integrations/followupboss/status",
            },
            409,
        )
    prior_auth = dict(fub.get("auth") or {})
    pending_existing = dict(prior_auth.get("oauthPending") or {})
    reuse_pending = False
    state: str
    nonce: str
    if pending_existing.get("state") and int(pending_existing.get("expiresAtEpoch") or 0) > now:
        p_uid, p_nonce, p_ok = _state_parse(str(pending_existing.get("state") or ""))
        if (
            p_ok
            and p_uid == uid
            and p_nonce
            and str(pending_existing.get("nonce") or "") == str(p_nonce)
        ):
            reuse_pending = True
            state = str(pending_existing["state"])
            nonce = str(p_nonce)
            refreshed_pending = dict(prior_auth.get("oauthPending") or {})
            refreshed_pending["expiresAtEpoch"] = now + 900
            refreshed_pending["createdAtEpoch"] = now
            auth_block = {**prior_auth, "oauthPending": refreshed_pending}
    if not reuse_pending:
        nonce = uuid.uuid4().hex
        state = _state_sign(uid, nonce)
        auth_block = dict(fub.get("auth") or {})
        auth_block["oauthPending"] = {
            "state": state,
            "nonce": nonce,
            "createdAtEpoch": now,
            "expiresAtEpoch": now + 900,
        }
    fub["connection"] = {
        "provider": "followupboss",
        "status": "oauth_pending",
        "mode": "oauth",
        "updatedAtEpoch": now,
    }
    fub["auth"] = auth_block
    fub.setdefault("audit", {})
    fub["audit"]["lastOauthStartAtEpoch"] = now

    db_body, db_status = save_fub_profile(uid, fub)
    if db_status >= 400:
        return json_response({"error": "db upsert failed", "detail": db_body}, 502 if db_status >= 500 else db_status)

    authorize_url, err_obj = _resolve_authorize_url(state, callback_url)
    if err_obj:
        return json_response({"ok": False, "state": state, "callbackUrl": callback_url, **err_obj}, 501)
    out = {"ok": True, "state": state, "authorizeUrl": authorize_url, "db": db_body}
    if reuse_pending:
        out["idempotent"] = True
    return json_response(out, 200)


def oauth_callback(request):
    state = _normalize_oauth_state_param(request.args.get("state"))
    code = (request.args.get("code") or "").strip()
    provider_error = (request.args.get("error") or "").strip()
    if not state:
        return json_response({"error": "missing state"}, 400)
    uid, nonce, state_ok = _state_parse(state)
    if not uid or not nonce or not state_ok:
        return json_response({"error": "invalid state", "phase": "oauth_state_parse"}, 401)

    if bridge_token.bridge_secret_configured():
        bc = bridge_token.verify_callback_bridge_token(request)
        if bc is None:
            return json_response(
                {
                    "error": "missing or invalid callback bridge token",
                    "phase": "oauth_bridge",
                    "hint": "OAuth callback must be invoked via the public API callback URL.",
                },
                401,
            )
        if bc.get("sub") != uid or bc.get("state") != state:
            return json_response({"error": "bridge token mismatch", "phase": "oauth_bridge"}, 401)

    _, fub = load_fub_profile_by_connection_id(uid)
    if fub is None:
        return json_response({"error": "followupboss not configured"}, 404)

    auth_pre = dict(fub.get("auth") or {})
    pending = dict(auth_pre.get("oauthPending") or {})
    access_ref = auth_pre.get("accessTokenRef")
    conn = dict(fub.get("connection") or {})
    st = conn.get("status")
    connected_like = st in ("connected", "connected_with_webhook_sync_issues", "needs_owner_for_webhooks")
    pending_state = str(pending.get("state") or "")
    pending_nonce = str(pending.get("nonce") or "")
    pending_mismatch = pending_state != state or pending_nonce != str(nonce)
    if pending_mismatch:
        if isinstance(access_ref, str) and access_ref and connected_like:
            if provider_error:
                return json_response({"error": "provider oauth error", "providerError": provider_error}, 400)
            return json_response(
                {
                    "ok": True,
                    "uid": uid,
                    "state": state,
                    "webhooks": dict(fub.get("webhooks") or {}),
                    "idempotent": True,
                },
                200,
            )
        if pending and int(pending.get("expiresAtEpoch") or 0) < now_epoch():
            return json_response({"error": "oauth state expired", "phase": "oauth_pending"}, 401)
        return json_response(
            {
                "error": "oauth state mismatch",
                "phase": "oauth_pending",
                "hint": "Restart connect from your app; an older authorize link or another tab may have replaced this session.",
            },
            401,
        )
    if int(pending.get("expiresAtEpoch") or 0) < now_epoch():
        return json_response({"error": "oauth state expired"}, 401)

    if provider_error:
        return json_response({"error": "provider oauth error", "providerError": provider_error}, 400)
    if not code:
        return json_response({"error": "missing code"}, 400)

    callback_url = _fub_callback_url(request)
    client = FubClient()
    token_body, token_status = client.exchange_code(code, callback_url, state)
    if token_status >= 400:
        return json_response({"error": "token_exchange_failed", "detail": token_body}, 502 if token_status >= 500 else token_status)

    access_token = token_body.get("access_token") or token_body.get("accessToken")
    refresh_token = token_body.get("refresh_token") or token_body.get("refreshToken")
    expires_in = token_body.get("expires_in") or token_body.get("expiresIn")
    if not isinstance(access_token, str) or not access_token:
        return json_response({"error": "invalid token response", "detail": token_body}, 502)

    access_ref, access_err = _put_fub_secret(f"fub-access-{uid}", access_token)
    if access_err:
        return json_response(
            {"error": "secret_persist_failed", "phase": "oauth_access_token", "detail": access_err},
            502,
        )
    refresh_ref = None
    if isinstance(refresh_token, str) and refresh_token:
        refresh_ref, refresh_err = _put_fub_secret(f"fub-refresh-{uid}", refresh_token)
        if refresh_err:
            return json_response(
                {"error": "secret_persist_failed", "phase": "oauth_refresh_token", "detail": refresh_err},
                502,
            )

    auth_block = dict(fub.get("auth") or {})
    auth_block["oauthPending"] = None
    auth_block["accessTokenRef"] = access_ref
    if refresh_ref:
        auth_block["refreshTokenRef"] = refresh_ref
    auth_block["tokenType"] = token_body.get("token_type")
    auth_block["scope"] = token_body.get("scope")
    auth_block["expiresAtEpoch"] = now_epoch() + int(expires_in or 3600)
    # global x-system key support for webhook signature checks
    auth_block["xSystemKeyRef"] = auth_block.get("xSystemKeyRef") or "env://FUB_X_SYSTEM_KEY"

    callback_base = public_integration_base_url(request)
    webhook_sync, sync_status = _ensure_all_webhooks(
        FubClient(access_token_ref=access_ref, api_key_ref=auth_block.get("apiKeyRef"), acting_uid=uid),
        uid,
        callback_base,
    )

    fub["auth"] = auth_block
    connect_status = "connected" if sync_status == 200 else "connected_with_webhook_sync_issues"
    if webhook_sync.get("needsOwner"):
        connect_status = "needs_owner_for_webhooks"
    fub["connection"] = {
        "provider": "followupboss",
        "status": connect_status,
        "mode": "oauth",
        "updatedAtEpoch": now_epoch(),
    }
    fub["webhooks"] = webhook_sync
    fub.setdefault("audit", {})
    fub["audit"]["lastOauthCallbackAtEpoch"] = now_epoch()
    save_fub_profile_by_connection_id(uid, fub)

    payload: dict = {"ok": True, "uid": uid, "state": state, "webhooks": webhook_sync}
    if not (isinstance(refresh_token, str) and refresh_token):
        payload["warning"] = {
            "code": "no_refresh_token_in_exchange",
            "todo": (
                "POST /integrations/followupboss/refresh will not work without a stored refresh token. "
                "Reconnect OAuth; ensure authorize URL uses response_type=auth_code per FUB docs."
            ),
        }
    return json_response(payload, 200 if sync_status in (200, 207) else 207)


def refresh(request):
    decoded, err, _token = resolve_realtor_bearer(request)
    if err:
        return integration_auth_error_response(err)
    uid = decoded["uid"]

    existing, status = load_realtor_profile(uid)
    maybe_err = _maybe_return_profile_load_error(existing, status)
    if maybe_err:
        return maybe_err
    fub = fub_config_from_profile(existing)
    if not fub:
        return json_response({"error": "followupboss not configured"}, 404)

    auth_block = dict(fub.get("auth") or {})
    refresh_ref = auth_block.get("refreshTokenRef")
    if not isinstance(refresh_ref, str) or not refresh_ref.strip():
        return json_response(
            {
                "error": "refresh_token_ref_missing",
                "todo": (
                    "No refreshTokenRef on the realtor profile (OAuth exchange may not have returned refresh_token, "
                    "or connect predates refresh storage). Disconnect and reconnect with authorize URL using "
                    "response_type=auth_code per Follow Up Boss docs."
                ),
            },
            400,
        )
    refresh_token = get_secret(refresh_ref, acting_uid=uid)
    if not refresh_token:
        return json_response(
            {
                "error": "refresh_token_secret_unreadable",
                "detail": "refreshTokenRef is set but the secret value is empty or could not be read for this uid.",
                "todo": "Verify secrets internal gateway + acs-sec scope for this realtor, or reconnect OAuth.",
            },
            400,
        )

    body, s = FubClient().refresh_token(refresh_token)
    if s >= 400:
        return json_response({"error": "token_refresh_failed", "detail": body}, 502 if s >= 500 else s)

    new_access = body.get("access_token")
    if isinstance(new_access, str) and new_access:
        ref, err = _put_fub_secret(f"fub-access-{uid}", new_access)
        if err:
            return json_response(
                {"error": "secret_persist_failed", "phase": "access_token", "detail": err},
                502,
            )
        auth_block["accessTokenRef"] = ref
    new_refresh = body.get("refresh_token")
    if isinstance(new_refresh, str) and new_refresh:
        ref, err = _put_fub_secret(f"fub-refresh-{uid}", new_refresh)
        if err:
            return json_response(
                {"error": "secret_persist_failed", "phase": "refresh_token", "detail": err},
                502,
            )
        auth_block["refreshTokenRef"] = ref

    auth_block["expiresAtEpoch"] = now_epoch() + int(body.get("expires_in") or 3600)
    fub["auth"] = auth_block
    fub.setdefault("audit", {})
    fub["audit"]["lastRefreshAtEpoch"] = now_epoch()

    db_body, db_status = save_fub_profile(uid, fub)
    if db_status >= 400:
        return json_response({"error": "db upsert failed", "detail": db_body}, 502 if db_status >= 500 else db_status)

    return json_response({"ok": True, "uid": uid, "db": db_body}, 200)


def connection_status(request):
    """GET — whether FUB is linked; use to hide OAuth start when already integrated."""
    decoded, err, _token = resolve_realtor_bearer(request)
    if err:
        return integration_auth_error_response(err)
    uid = decoded["uid"]

    existing, status = load_realtor_profile(uid)
    maybe_err = _maybe_return_profile_load_error(existing, status)
    if maybe_err:
        return maybe_err

    fub = fub_config_from_profile(existing) or {}
    conn = dict(fub.get("connection") or {})
    st = conn.get("status")
    integrated = _fub_is_integrated(fub)
    auth_block = dict(fub.get("auth") or {})
    rr = auth_block.get("refreshTokenRef")
    ar = auth_block.get("accessTokenRef")
    return json_response(
        {
            "ok": True,
            "uid": uid,
            "connectionStatus": st,
            "integrated": integrated,
            "canOauthStart": not integrated,
            "oauthStartPath": "/integrations/followupboss/oauth/start",
            "disconnectPath": "/integrations/followupboss/disconnect",
            "hasAccessTokenRef": isinstance(ar, str) and bool(ar.strip()),
            "hasRefreshTokenRef": isinstance(rr, str) and bool(rr.strip()),
        },
        200,
    )


def disconnect(request):
    decoded, err, _token = resolve_realtor_bearer(request)
    if err:
        return integration_auth_error_response(err)
    uid = decoded["uid"]

    existing, status = load_realtor_profile(uid)
    maybe_err = _maybe_return_profile_load_error(existing, status)
    if maybe_err:
        return maybe_err
    fub = fub_config_from_profile(existing)
    if not fub:
        return json_response({"error": "followupboss not configured"}, 404)

    conn = dict(fub.get("connection") or {})
    if conn.get("status") == "disconnected":
        return json_response(
            {
                "ok": True,
                "uid": uid,
                "idempotent": True,
                "webhooksBefore": dict(fub.get("webhooks") or {}),
            },
            200,
        )

    auth_block = dict(fub.get("auth") or {})
    client = FubClient(access_token_ref=auth_block.get("accessTokenRef"), api_key_ref=auth_block.get("apiKeyRef"), acting_uid=uid)
    webhooks = dict(fub.get("webhooks") or {})
    # best effort cleanup
    listed, ls = client.list_webhooks()
    if ls < 400:
        items = listed if isinstance(listed, list) else listed.get("_embedded", {}).get("webhooks", []) if isinstance(listed, dict) else []
        callback_base = public_integration_base_url(request)
        target = f"{callback_base}/integrations/webhooks/followupboss?connectionId={uid}"
        for w in items if isinstance(items, list) else []:
            if isinstance(w, dict) and w.get("url") == target and w.get("id") is not None:
                client.delete_webhook(w.get("id"))

    fub["connection"] = {
        "provider": "followupboss",
        "status": "disconnected",
        "mode": "oauth",
        "updatedAtEpoch": now_epoch(),
    }
    fub["webhooks"] = {}
    fub["auth"] = {
        "xSystemKeyRef": auth_block.get("xSystemKeyRef") or "env://FUB_X_SYSTEM_KEY"
    }
    fub.setdefault("audit", {})
    fub["audit"]["lastDisconnectAtEpoch"] = now_epoch()

    db_body, db_status = save_fub_profile(uid, fub)
    if db_status >= 400:
        return json_response({"error": "db upsert failed", "detail": db_body}, 502 if db_status >= 500 else db_status)
    return json_response({"ok": True, "uid": uid, "db": db_body, "webhooksBefore": webhooks}, 200)


def resync_webhooks(request):
    decoded, err, _token = resolve_realtor_bearer(request)
    if err:
        return integration_auth_error_response(err)
    uid = decoded["uid"]

    existing, status = load_realtor_profile(uid)
    maybe_err = _maybe_return_profile_load_error(existing, status)
    if maybe_err:
        return maybe_err
    fub = fub_config_from_profile(existing)
    if not fub:
        return json_response({"error": "followupboss not configured"}, 404)
    auth_block = dict(fub.get("auth") or {})
    access_ref = auth_block.get("accessTokenRef")
    if not isinstance(access_ref, str) or not access_ref:
        return json_response({"error": "access token ref missing"}, 400)

    callback_base = public_integration_base_url(request)
    result, sync_status = _ensure_all_webhooks(
        FubClient(access_token_ref=access_ref, api_key_ref=auth_block.get("apiKeyRef"), acting_uid=uid),
        uid,
        callback_base,
    )
    fub["webhooks"] = result
    fub.setdefault("audit", {})
    fub["audit"]["lastWebhookResyncAtEpoch"] = now_epoch()
    save_fub_profile(uid, fub)
    return json_response({"ok": sync_status in (200, 207), "uid": uid, "webhooks": result}, 200 if sync_status in (200, 207) else sync_status)


def list_registered_webhooks(request):
    """GET raw FUB /v1/webhooks for the connected realtor (read-only)."""
    decoded, err, _token = resolve_realtor_bearer(request)
    if err:
        return integration_auth_error_response(err)
    uid = decoded["uid"]

    existing, status = load_realtor_profile(uid)
    maybe_err = _maybe_return_profile_load_error(existing, status)
    if maybe_err:
        return maybe_err
    fub = fub_config_from_profile(existing)
    if not fub:
        return json_response({"error": "followupboss not configured"}, 404)
    auth_block = dict(fub.get("auth") or {})
    access_ref = auth_block.get("accessTokenRef")
    if not isinstance(access_ref, str) or not access_ref:
        return json_response({"error": "access token ref missing", "todo": "Complete OAuth connect first."}, 400)

    api_key_ref = auth_block.get("apiKeyRef")
    access_plain = get_secret(access_ref, acting_uid=uid)
    api_plain = (
        get_secret(api_key_ref, acting_uid=uid) if isinstance(api_key_ref, str) and api_key_ref else None
    )
    if not access_plain and not api_plain:
        return json_response(
            {
                "ok": False,
                "httpStatus": 503,
                "error": "fub_credentials_unavailable",
                "detail": "Access token and API key could not be loaded from secret storage.",
                "accessTokenRefPresent": True,
                "apiKeyRefPresent": bool(isinstance(api_key_ref, str) and bool(api_key_ref.strip())),
                "likelyCause": (
                    "acs-sec:// reads use the same platform OIDC token as writes. If integration-bridge env "
                    "SECRETS_INTERNAL_JWT_AUDIENCE is wrong or unset, secrets-bridge returns 401 and get_secret "
                    "returns empty — not a missing FUB token."
                ),
                "todo": (
                    "Apply terraform so integration-bridge gets SECRETS_INTERNAL_JWT_AUDIENCE = secrets-bridge "
                    "Cloud Function URL (output secrets_bridge_invoker_audience). Redeploy integration-bridge. "
                    "Confirm secrets-bridge accepts that audience (ACS_SECRETS_GATEWAY_HOSTNAME / platform_auth). "
                    "Then gcloud logging read stderr for integration-bridge should stop showing "
                    "'invalid platform identity token' on secrets read/write."
                ),
            },
            503,
        )

    raw, st = FubClient(access_token_ref=access_ref, api_key_ref=auth_block.get("apiKeyRef"), acting_uid=uid).list_webhooks()
    return json_response({"ok": st < 400, "httpStatus": st, "fub": raw}, 200 if st < 400 else st)

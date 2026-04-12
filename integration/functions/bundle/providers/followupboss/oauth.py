import hashlib
import hmac
import os
import re
import urllib.parse
import uuid

from providers.followupboss.client import FubClient
from providers.followupboss.constants import ALL_WEBHOOK_EVENTS
from store.authn import resolve_realtor_bearer
from store.common import json_response, now_epoch, public_integration_base_url
from store.profile_repo import (
    fub_config_from_profile,
    load_fub_profile_by_connection_id,
    load_realtor_profile,
    save_fub_profile,
    save_fub_profile_by_connection_id,
)
from store.secret_repo import get_secret, put_secret

_STATE_RE = re.compile(r"^[a-zA-Z0-9._-]{8,512}$")


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
    # TODO: confirm exact Follow Up Boss scope and response parameters for your registered app.
    params = [
        f"state={urllib.parse.quote(state, safe='')}",
        f"redirect_uri={urllib.parse.quote(callback_url, safe='')}",
    ]
    if client_id:
        params.append(f"client_id={client_id}")
    if "response_type=" not in base:
        params.append("response_type=code")
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
        return json_response(
            {"error": err, "phase": "integration_auth"},
            401 if err != "forbidden" else 403,
        )

    uid = decoded["uid"]
    nonce = uuid.uuid4().hex
    state = _state_sign(uid, nonce)
    now = now_epoch()
    callback_url = _fub_callback_url(request)

    existing, status = load_realtor_profile(uid)
    maybe_err = _maybe_return_profile_load_error(existing, status)
    if maybe_err:
        return maybe_err

    fub = fub_config_from_profile(existing) or {}
    fub["connection"] = {
        "provider": "followupboss",
        "status": "oauth_pending",
        "mode": "oauth",
        "updatedAtEpoch": now,
    }
    auth_block = dict(fub.get("auth") or {})
    auth_block["oauthPending"] = {
        "state": state,
        "nonce": nonce,
        "createdAtEpoch": now,
        "expiresAtEpoch": now + 900,
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
    return json_response({"ok": True, "state": state, "authorizeUrl": authorize_url, "db": db_body}, 200)


def oauth_callback(request):
    state = (request.args.get("state") or "").strip()
    code = (request.args.get("code") or "").strip()
    provider_error = (request.args.get("error") or "").strip()
    if not state:
        return json_response({"error": "missing state"}, 400)
    uid, nonce, state_ok = _state_parse(state)
    if not uid or not nonce or not state_ok:
        return json_response({"error": "invalid state"}, 401)

    _, fub = load_fub_profile_by_connection_id(uid)
    if fub is None:
        return json_response({"error": "followupboss not configured"}, 404)

    pending = dict((fub.get("auth") or {}).get("oauthPending") or {})
    if pending.get("state") != state or pending.get("nonce") != nonce:
        return json_response({"error": "oauth state mismatch"}, 401)
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

    access_token = token_body.get("access_token")
    refresh_token = token_body.get("refresh_token")
    expires_in = token_body.get("expires_in")
    if not isinstance(access_token, str) or not access_token:
        return json_response({"error": "invalid token response", "detail": token_body}, 502)

    access_ref = put_secret(f"fub-access-{uid}", access_token)
    refresh_ref = None
    if isinstance(refresh_token, str) and refresh_token:
        refresh_ref = put_secret(f"fub-refresh-{uid}", refresh_token)

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
        FubClient(access_token_ref=access_ref, api_key_ref=auth_block.get("apiKeyRef")),
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

    return json_response({"ok": True, "uid": uid, "state": state, "webhooks": webhook_sync}, 200 if sync_status in (200, 207) else 207)


def refresh(request):
    decoded, err, _token = resolve_realtor_bearer(request)
    if err:
        return json_response({"error": err}, 401 if err != "forbidden" else 403)
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
    refresh_token = get_secret(refresh_ref or "")
    if not refresh_token:
        return json_response(
            {
                "error": "refresh token missing",
                "todo": "Reconnect account to obtain refresh token or ensure secret ref exists.",
            },
            400,
        )

    body, s = FubClient().refresh_token(refresh_token)
    if s >= 400:
        return json_response({"error": "token_refresh_failed", "detail": body}, 502 if s >= 500 else s)

    new_access = body.get("access_token")
    if isinstance(new_access, str) and new_access:
        auth_block["accessTokenRef"] = put_secret(f"fub-access-{uid}", new_access)
    new_refresh = body.get("refresh_token")
    if isinstance(new_refresh, str) and new_refresh:
        auth_block["refreshTokenRef"] = put_secret(f"fub-refresh-{uid}", new_refresh)

    auth_block["expiresAtEpoch"] = now_epoch() + int(body.get("expires_in") or 3600)
    fub["auth"] = auth_block
    fub.setdefault("audit", {})
    fub["audit"]["lastRefreshAtEpoch"] = now_epoch()

    db_body, db_status = save_fub_profile(uid, fub)
    if db_status >= 400:
        return json_response({"error": "db upsert failed", "detail": db_body}, 502 if db_status >= 500 else db_status)

    return json_response({"ok": True, "uid": uid, "db": db_body}, 200)


def disconnect(request):
    decoded, err, _token = resolve_realtor_bearer(request)
    if err:
        return json_response({"error": err}, 401 if err != "forbidden" else 403)
    uid = decoded["uid"]

    existing, status = load_realtor_profile(uid)
    maybe_err = _maybe_return_profile_load_error(existing, status)
    if maybe_err:
        return maybe_err
    fub = fub_config_from_profile(existing)
    if not fub:
        return json_response({"error": "followupboss not configured"}, 404)

    auth_block = dict(fub.get("auth") or {})
    client = FubClient(access_token_ref=auth_block.get("accessTokenRef"), api_key_ref=auth_block.get("apiKeyRef"))
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
        return json_response({"error": err}, 401 if err != "forbidden" else 403)
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
        FubClient(access_token_ref=access_ref, api_key_ref=auth_block.get("apiKeyRef")),
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
        return json_response({"error": err}, 401 if err != "forbidden" else 403)
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

    raw, st = FubClient(access_token_ref=access_ref, api_key_ref=auth_block.get("apiKeyRef")).list_webhooks()
    return json_response({"ok": st < 400, "httpStatus": st, "fub": raw}, 200 if st < 400 else st)

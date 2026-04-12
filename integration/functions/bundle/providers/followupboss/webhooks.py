import base64
import hashlib
import hmac
import json
import re
import uuid

from dispatcher.core_client import send_state_to_core
from dispatcher.egress import dispatch_provider_actions, extract_actions_from_state, outbound_enabled
from providers.followupboss.client import FubClient
from store.authn import resolve_realtor_bearer
from store.common import json_response
from store.profile_repo import (
    load_fub_profile_by_connection_id,
    put_event_ledger,
    update_event_status,
)
from store.secret_repo import get_secret

_CONNECTION_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")


def _signature_ok(raw_body: bytes, header_sig: str | None, x_system_key: str) -> bool:
    if not header_sig or not x_system_key:
        return False
    msg = base64.b64encode(raw_body)
    expected = hmac.new(x_system_key.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header_sig.strip())


def _process_webhook_event(connection_id: str, fub: dict, event_body: dict):
    """Shared pipeline after signature (ingress) or Firebase auth (test)."""
    auth = dict(fub.get("auth") or {})

    event_id = event_body.get("eventId") if isinstance(event_body.get("eventId"), str) else str(uuid.uuid4())
    inserted, _ = put_event_ledger(connection_id, event_id, event_body)
    if not inserted:
        return json_response({"ok": True, "duplicate": True, "eventId": event_id}, 200)

    state = _to_acs_state(event_body, connection_id)
    core_body, core_status = send_state_to_core(state)
    if core_status >= 400:
        update_event_status(connection_id, event_id, "core_error", core_body)
        return json_response({"ok": True, "accepted": True, "eventId": event_id, "status": "core_error"}, 200)

    result_state = core_body.get("state") if isinstance(core_body, dict) else {}
    actions = extract_actions_from_state(result_state if isinstance(result_state, dict) else {})
    if outbound_enabled() and actions:
        outbound = dispatch_provider_actions("followupboss", connection_id, actions)
        update_event_status(connection_id, event_id, "processed_with_outbound", outbound)
    else:
        update_event_status(connection_id, event_id, "processed", {"actions": len(actions)})

    uri = event_body.get("uri")
    if isinstance(uri, str) and uri:
        client = FubClient(
            access_token_ref=auth.get("accessTokenRef"),
            api_key_ref=auth.get("apiKeyRef"),
            acting_uid=connection_id,
        )
        _r, _s = client.get_by_uri(uri)
        update_event_status(connection_id, event_id, "processed", {"fetchedUri": _s < 400})

    return json_response({"ok": True, "accepted": True, "eventId": event_id}, 200)


def _to_acs_state(event_body: dict, connection_id: str) -> dict:
    event_type = event_body.get("event") if isinstance(event_body.get("event"), str) else "unknown"
    correlation = event_body.get("eventId") if isinstance(event_body.get("eventId"), str) else str(uuid.uuid4())
    return {
        "state_version": 1,
        "correlation_id": correlation,
        "tenant_id": None,
        "user_id": connection_id,
        "source": {"provider": "followupboss", "event_type": event_type},
        "payload": event_body,
        "metadata": {"connection_id": connection_id},
    }


def webhook_ingress(request):
    raw = request.get_data(cache=False, as_text=False) or b""
    connection_id = request.args.get("connectionId") or request.args.get("connection_id")
    if not connection_id or not _CONNECTION_ID_RE.match(connection_id):
        return json_response({"error": "connectionId query parameter required"}, 400)

    _, fub = load_fub_profile_by_connection_id(connection_id)
    if not fub:
        return json_response({"error": "followupboss not configured"}, 404)

    auth = dict(fub.get("auth") or {})
    x_system_ref = auth.get("xSystemKeyRef") or "env://FUB_X_SYSTEM_KEY"
    x_system_key = get_secret(x_system_ref)
    if not isinstance(x_system_key, str) or not x_system_key:
        return json_response(
            {
                "error": "xSystemKey unavailable",
                "todo": "Set FUB_X_SYSTEM_KEY env or persist xSystemKeyRef secret.",
            },
            503,
        )

    if not _signature_ok(raw, request.headers.get("FUB-Signature"), x_system_key):
        return json_response({"error": "invalid FUB-Signature"}, 401)

    try:
        event_body = json.loads(raw.decode("utf-8") if raw else "{}")
    except json.JSONDecodeError:
        return json_response({"error": "invalid JSON body"}, 400)
    if not isinstance(event_body, dict):
        return json_response({"error": "JSON object body required"}, 400)

    return _process_webhook_event(connection_id, fub, event_body)


def webhook_test(request):
    """POST same JSON body as FUB webhooks; requires Firebase realtor token; uses token uid as connectionId."""
    decoded, err, _token = resolve_realtor_bearer(request)
    if err:
        return json_response({"error": err}, 401 if err != "forbidden" else 403)
    uid = decoded["uid"]

    raw = request.get_data(cache=False, as_text=False) or b""
    try:
        event_body = json.loads(raw.decode("utf-8") if raw else "{}")
    except json.JSONDecodeError:
        return json_response({"error": "invalid JSON body"}, 400)
    if not isinstance(event_body, dict):
        return json_response({"error": "JSON object body required"}, 400)

    _, fub = load_fub_profile_by_connection_id(uid)
    if not fub:
        return json_response({"error": "followupboss not configured"}, 404)

    return _process_webhook_event(uid, fub, event_body)

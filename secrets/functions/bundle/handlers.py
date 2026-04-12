from __future__ import annotations

import json
from typing import Any

import gsm_store
import naming
from platform_auth import require_acting_uid, verify_platform_request


def json_response(payload: dict, status: int):
    return (json.dumps(payload), status, {"Content-Type": "application/json"})


def _parse_body(request) -> dict[str, Any]:
    raw = request.get_data(as_text=True) or "{}"
    try:
        out = json.loads(raw)
        return out if isinstance(out, dict) else {}
    except json.JSONDecodeError:
        return {}


def handle_write(request):
    _claims, plat_err = verify_platform_request(request)
    if plat_err:
        return json_response(plat_err[0], plat_err[1])
    body = _parse_body(request)
    scope = (body.get("scope") or "").strip()
    scope_id = (body.get("scopeId") or "").strip()
    key = (body.get("key") or "").strip()
    value = body.get("value")
    if scope != "realtor":
        return json_response({"error": "unsupported scope"}, 400)
    if not scope_id or not key:
        return json_response({"error": "scopeId and key are required"}, 400)
    if not isinstance(value, str) or not value:
        return json_response({"error": "value must be a non-empty string"}, 400)
    _a, act_err = require_acting_uid(request, scope_id)
    if act_err:
        return json_response(act_err[0], act_err[1])
    try:
        secret_id = naming.physical_secret_id(scope, scope_id, key)
    except ValueError as e:
        return json_response({"error": str(e)}, 400)
    try:
        resource, skipped = gsm_store.write_version(secret_id, value)
    except Exception as e:
        return json_response({"error": "secret write failed", "detail": str(e)}, 502)
    ref = naming.ref_for_secret_id(secret_id)
    payload: dict[str, Any] = {"ref": ref, "secretResource": resource}
    if skipped:
        payload["idempotent"] = True
    return json_response(payload, 200)


def handle_read(request):
    _claims, plat_err = verify_platform_request(request)
    if plat_err:
        return json_response(plat_err[0], plat_err[1])
    body = _parse_body(request)
    ref = (body.get("ref") or "").strip()
    scope = (body.get("scope") or "").strip()
    scope_id = (body.get("scopeId") or "").strip()
    key = (body.get("key") or "").strip()

    secret_id: str | None = None
    owner_scope_id: str | None = None

    if ref:
        secret_id = naming.parse_ref(ref)
        if not secret_id:
            return json_response({"error": "invalid ref"}, 400)
        owner_scope_id = naming.scope_id_from_secret_id(secret_id)
        if not owner_scope_id:
            return json_response({"error": "invalid ref format"}, 400)
    elif scope and scope_id and key:
        if scope != "realtor":
            return json_response({"error": "unsupported scope"}, 400)
        _a, act_err = require_acting_uid(request, scope_id)
        if act_err:
            return json_response(act_err[0], act_err[1])
        try:
            secret_id = naming.physical_secret_id(scope, scope_id, key)
        except ValueError as e:
            return json_response({"error": str(e)}, 400)
        owner_scope_id = scope_id
    else:
        return json_response({"error": "provide ref or (scope, scopeId, key)"}, 400)

    if owner_scope_id:
        _a, act_err = require_acting_uid(request, owner_scope_id)
        if act_err:
            return json_response(act_err[0], act_err[1])

    val = gsm_store.read_latest(secret_id or "")
    if val is None:
        return json_response({"error": "not found"}, 404)
    return json_response({"value": val}, 200)


def handle_delete(request):
    _claims, plat_err = verify_platform_request(request)
    if plat_err:
        return json_response(plat_err[0], plat_err[1])
    body = _parse_body(request)
    ref = (body.get("ref") or "").strip()
    if not ref:
        return json_response({"error": "ref is required"}, 400)
    secret_id = naming.parse_ref(ref)
    if not secret_id:
        return json_response({"error": "invalid ref"}, 400)
    owner_scope_id = naming.scope_id_from_secret_id(secret_id)
    if not owner_scope_id:
        return json_response({"error": "invalid ref format"}, 400)
    _a, act_err = require_acting_uid(request, owner_scope_id)
    if act_err:
        return json_response(act_err[0], act_err[1])
    ok = gsm_store.delete_secret(secret_id)
    if not ok:
        return json_response({"ok": True, "idempotent": True}, 200)
    return json_response({"ok": True}, 200)

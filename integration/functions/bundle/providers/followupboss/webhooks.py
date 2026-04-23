import base64
import copy
import hashlib
import hmac
import json
import re
import uuid

from dispatcher.core_client import send_state_to_core
from dispatcher.execution_policy import execution_policy_from_profile
from dispatcher.egress import dispatch_provider_actions, extract_actions_from_state, outbound_enabled
from dispatcher.outbound_policy import partition_outbound_actions
from dispatcher.webhook_workflow_map import resolve_workflow_ids_for_webhook
from providers.followupboss.webhook_payload_enrich import merge_fub_person_from_api
from schema.canonical_webhook import build_canonical_webhook_event_v1, to_acs_state_v1
from store.authn import resolve_realtor_bearer
from store.common import integration_auth_error_response, json_response
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


def _workflow_debug_payload(*, core_status: int, core_body: dict) -> dict:
    """Subset of core /run response for realtor-only webhook_test debugging (lite UI log)."""
    out: dict = {"core_http_status": core_status}
    out["core_run"] = {
        "status": core_body.get("status"),
        "error": core_body.get("error"),
    }
    st = core_body.get("state")
    if isinstance(st, dict):
        meta = st.get("metadata") if isinstance(st.get("metadata"), dict) else {}
        core_m = meta.get("core") if isinstance(meta.get("core"), dict) else {}
        wf_demo = meta.get("workflowDemo") if isinstance(meta.get("workflowDemo"), dict) else {}
        errs = st.get("errors") if isinstance(st.get("errors"), list) else []
        oa = meta.get("outboundActions")
        skipped_ob = meta.get("skipped_outbound")
        out["state"] = {
            "correlation_id": st.get("correlation_id"),
            "metadata_core": core_m,
            "metadata_workflowDemo": wf_demo,
            "metadata_execution_policy": meta.get("execution_policy"),
            "metadata_workflow_routing": meta.get("workflow_routing"),
            "metadata_skipped_outbound": skipped_ob,
            "outbound_actions_count": len(oa) if isinstance(oa, list) else 0,
            "skipped_outbound_count": len(skipped_ob) if isinstance(skipped_ob, list) else 0,
            "errors": errs[:20],
        }
    return out


def _merge_skipped_outbound_into_state(state: dict, skipped: list[dict]) -> None:
    if not skipped or not isinstance(state, dict):
        return
    meta = dict(state.get("metadata") or {})
    prior = meta.get("skipped_outbound")
    merged: list[dict] = []
    if isinstance(prior, list):
        merged.extend(p for p in prior if isinstance(p, dict))
    merged.extend(skipped)
    meta["skipped_outbound"] = merged
    state["metadata"] = meta


def _process_webhook_event(
    connection_id: str,
    fub: dict,
    event_body: dict,
    *,
    profile: dict | None = None,
    workflow_id: str | None = None,
    include_workflow_debug: bool = False,
):
    """Shared pipeline after signature (ingress) or Firebase auth (test).

    Optional ``workflow_id`` query param (e.g. ``demo.joke_to_profile_v1``) is forwarded to core for testing.
    """
    event_id = event_body.get("eventId") if isinstance(event_body.get("eventId"), str) else str(uuid.uuid4())
    inserted, _ = put_event_ledger(connection_id, event_id, event_body)
    if not inserted:
        dup: dict = {"ok": True, "duplicate": True, "eventId": event_id}
        if include_workflow_debug:
            dup["workflow_debug"] = {"note": "duplicate event_id; core run skipped"}
        return json_response(dup, 200)

    policy = execution_policy_from_profile(profile)
    # Core-run should not call back into integration for CRM reads; hydrate here (tokens already loaded).
    enrich_status = merge_fub_person_from_api(connection_id, fub, event_body)

    canonical = build_canonical_webhook_event_v1(
        provider="followupboss",
        connection_id=connection_id,
        raw_provider_body=event_body,
    )
    state = to_acs_state_v1(canonical, connection_id=connection_id)
    meta = dict(state.get("metadata") or {})
    meta["execution_policy"] = policy
    meta["integrationEnrich"] = enrich_status
    state["metadata"] = meta

    event_type = event_body.get("event") if isinstance(event_body.get("event"), str) else "unknown"
    wf_explicit = (workflow_id or "").strip() or None
    wf_ids = resolve_workflow_ids_for_webhook(
        "followupboss",
        event_type,
        explicit_workflow_id=wf_explicit,
        policy=policy,
    )

    if not wf_ids:
        update_event_status(
            connection_id,
            event_id,
            "processed_no_workflow",
            {"eventType": event_type, "reason": "no_workflow_mapping"},
        )
        body: dict = {
            "ok": True,
            "accepted": True,
            "eventId": event_id,
            "status": "processed_no_workflow",
            "workflows": [],
        }
        if include_workflow_debug:
            body["workflow_debug"] = {"note": "no workflow_ids resolved for event type; core not invoked"}
        return json_response(body, 200)

    dispatch_records: list[dict] = []
    last_core_body: dict = {}
    last_core_status = 200
    all_actions: list[dict] = []
    any_core_error = False

    for wf in wf_ids:
        state_run = copy.deepcopy(state)
        core_body, core_status = send_state_to_core(state_run, workflow_id=wf)
        last_core_body = core_body if isinstance(core_body, dict) else {}
        last_core_status = core_status
        rec: dict = {"workflow_id": wf, "core_http_status": core_status}
        if core_status >= 400:
            any_core_error = True
            rec["error"] = last_core_body.get("error") if isinstance(last_core_body, dict) else "core_error"
        dispatch_records.append(rec)
        if core_status < 400:
            rs = last_core_body.get("state") if isinstance(last_core_body.get("state"), dict) else {}
            all_actions.extend(extract_actions_from_state(rs))

    meta_dispatch = dict(state.get("metadata") or {})
    meta_dispatch["webhook_dispatch"] = {"runs": dispatch_records}
    state["metadata"] = meta_dispatch

    all_core_failed = bool(dispatch_records) and all(
        d.get("core_http_status", 500) >= 400 for d in dispatch_records
    )
    if all_core_failed:
        update_event_status(
            connection_id,
            event_id,
            "core_error",
            {"dispatch": dispatch_records, "last_core_response": last_core_body},
        )
        err_payload: dict = {
            "ok": True,
            "accepted": True,
            "eventId": event_id,
            "status": "core_error",
            "workflows": wf_ids,
            "webhook_dispatch": dispatch_records,
        }
        if include_workflow_debug:
            err_payload["workflow_debug"] = _workflow_debug_payload(
                core_status=last_core_status, core_body=last_core_body
            )
            err_payload["workflow_debug"]["dispatch"] = dispatch_records
        return json_response(err_payload, 200)

    # Merge outbound from all successful runs into one partition/dispatch (same connection).
    to_apply, skipped_policy = partition_outbound_actions(all_actions, policy)
    skipped: list[dict] = list(skipped_policy)
    if not outbound_enabled():
        for a in to_apply:
            skipped.append({"action": a, "reason": "outbound_egress_globally_disabled"})
        to_apply = []
    # Attach skipped_outbound to the last result state if present (debug / realtor UI).
    result_state = last_core_body.get("state") if isinstance(last_core_body.get("state"), dict) else None
    rs = result_state if isinstance(result_state, dict) else None
    if skipped and isinstance(last_core_body, dict) and isinstance(rs, dict):
        _merge_skipped_outbound_into_state(rs, skipped)
        last_core_body["state"] = rs
    if outbound_enabled() and to_apply:
        outbound = dispatch_provider_actions("followupboss", connection_id, to_apply)
        detail = dict(outbound) if isinstance(outbound, dict) else {"detail": outbound}
        detail["webhook_dispatch"] = dispatch_records
        if any_core_error:
            detail["partial_core_error"] = True
        if skipped:
            detail["skipped_outbound_count"] = len(skipped)
        update_event_status(connection_id, event_id, "processed_with_outbound", detail)
    else:
        detail_end: dict = {
            "actions": len(all_actions),
            "applied": len(to_apply),
            "skipped": len(skipped),
            "webhook_dispatch": dispatch_records,
        }
        if any_core_error:
            detail_end["partial_core_error"] = True
        update_event_status(connection_id, event_id, "processed", detail_end)

    ok_payload: dict = {
        "ok": True,
        "accepted": True,
        "eventId": event_id,
        "workflows": wf_ids,
        "webhook_dispatch": dispatch_records,
    }
    if any_core_error:
        ok_payload["status"] = "partial_core_error"
    if include_workflow_debug:
        ok_payload["workflow_debug"] = _workflow_debug_payload(core_status=last_core_status, core_body=last_core_body)
        ok_payload["workflow_debug"]["dispatch"] = dispatch_records
    return json_response(ok_payload, 200)


def webhook_ingress(request):
    raw = request.get_data(cache=False, as_text=False) or b""
    connection_id = request.args.get("connectionId") or request.args.get("connection_id")
    if not connection_id or not _CONNECTION_ID_RE.match(connection_id):
        return json_response({"error": "connectionId query parameter required"}, 400)

    profile, fub = load_fub_profile_by_connection_id(connection_id)
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

    wf = (request.args.get("workflowId") or request.args.get("workflow_id") or "").strip()
    return _process_webhook_event(
        connection_id,
        fub,
        event_body,
        profile=profile,
        workflow_id=wf or None,
    )


def webhook_test(request):
    """POST same JSON body as FUB webhooks; requires Firebase realtor token; uses token uid as connectionId."""
    decoded, err, _token = resolve_realtor_bearer(request)
    if err:
        return integration_auth_error_response(err)
    uid = decoded["uid"]

    raw = request.get_data(cache=False, as_text=False) or b""
    try:
        event_body = json.loads(raw.decode("utf-8") if raw else "{}")
    except json.JSONDecodeError:
        return json_response({"error": "invalid JSON body"}, 400)
    if not isinstance(event_body, dict):
        return json_response({"error": "JSON object body required"}, 400)

    profile, fub = load_fub_profile_by_connection_id(uid)
    if not fub:
        return json_response({"error": "followupboss not configured"}, 404)

    wf = (request.args.get("workflowId") or request.args.get("workflow_id") or "").strip()
    return _process_webhook_event(
        uid,
        fub,
        event_body,
        profile=profile,
        workflow_id=wf or None,
        include_workflow_debug=True,
    )

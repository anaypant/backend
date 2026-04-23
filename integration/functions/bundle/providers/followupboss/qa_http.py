"""HTTP QA: deterministic checks for FUB mapping + webhook routing (no live FUB API)."""

from __future__ import annotations

from typing import Any

from dispatcher.webhook_workflow_map import resolve_workflow_ids_for_webhook
from providers.followupboss.mapping.outbound import acs_outbound_action_to_fub_request
from schema.canonical_webhook import build_canonical_webhook_event_v1, to_acs_state_v1, validate_canonical_webhook_event_v1
from store.authn import resolve_realtor_bearer
from store.common import integration_auth_error_response, json_response


def _run_integration_unit_checks() -> dict[str, Any]:
    results: list[dict[str, Any]] = []

    raw = {"eventId": "evt-qa-1", "event": "peopleCreated", "uri": "https://api.followupboss.com/v1/people/7"}
    canon = build_canonical_webhook_event_v1(provider="followupboss", connection_id="uid-qa", raw_provider_body=raw)
    ok, err = validate_canonical_webhook_event_v1(canon)
    if not ok:
        results.append({"id": "canonical.validate", "ok": False, "detail": err or "validate failed"})
    else:
        results.append({"id": "canonical.validate", "ok": True, "detail": ""})

    st = to_acs_state_v1(canon, connection_id="uid-qa")
    if st.get("correlation_id") != "evt-qa-1":
        results.append({"id": "canonical.to_acs.correlation", "ok": False, "detail": f"{st.get('correlation_id')!r}"})
    elif st.get("payload", {}).get("event") != "peopleCreated":
        results.append({"id": "canonical.to_acs.payload", "ok": False, "detail": "payload.event mismatch"})
    elif (st.get("metadata") or {}).get("canonical_webhook", {}).get("eventType") != "peopleCreated":
        results.append({"id": "canonical.to_acs.metadata", "ok": False, "detail": "canonical_webhook metadata"})
    else:
        results.append({"id": "canonical.to_acs", "ok": True, "detail": ""})

    wids = resolve_workflow_ids_for_webhook("followupboss", "peopleCreated", explicit_workflow_id=None, policy={})
    if wids != ["contact.enrichment_v1"]:
        results.append({"id": "webhook_map.peopleCreated", "ok": False, "detail": f"{wids!r}"})
    else:
        results.append({"id": "webhook_map.peopleCreated", "ok": True, "detail": ""})

    wids2 = resolve_workflow_ids_for_webhook("followupboss", "notesCreated", explicit_workflow_id=None, policy={})
    if wids2:
        results.append({"id": "webhook_map.notesCreated_empty", "ok": False, "detail": f"expected empty got {wids2!r}"})
    else:
        results.append({"id": "webhook_map.notesCreated_empty", "ok": True, "detail": ""})

    ex = resolve_workflow_ids_for_webhook(
        "followupboss",
        "ignored",
        explicit_workflow_id="demo.joke_to_profile_v1",
        policy={},
    )
    if ex != ["demo.joke_to_profile_v1"]:
        results.append({"id": "webhook_map.explicit_override", "ok": False, "detail": f"{ex!r}"})
    else:
        results.append({"id": "webhook_map.explicit_override", "ok": True, "detail": ""})

    ob = acs_outbound_action_to_fub_request({"name": "createNote", "payload": {"personId": 1, "body": "x"}})
    if not isinstance(ob, dict) or ob.get("fubOperation") != "POST notes":
        results.append({"id": "outbound.createNote", "ok": False, "detail": f"{ob!r}"})
    else:
        results.append({"id": "outbound.createNote", "ok": True, "detail": ""})

    passed = sum(1 for r in results if r.get("ok") is True)
    failed = len(results) - passed
    return {"ok": failed == 0, "results": results, "summary": {"passed": passed, "failed": failed, "total": len(results)}}


def qa_unit_checks(request):
    if request.method != "POST":
        return json_response({"error": "method not allowed"}, 405)
    decoded, err, _token = resolve_realtor_bearer(request)
    if err:
        return integration_auth_error_response(err)
    _uid = decoded["uid"]
    payload = _run_integration_unit_checks()
    return json_response(payload, 200)

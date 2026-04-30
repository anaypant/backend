"""
Direct Follow Up Boss people/notes/tasks/tags operations exposed as HTTP handlers.

Each function accepts a Flask-compatible request object, authenticates the realtor via
Firebase Bearer token, resolves the FUB OAuth client, and proxies the operation to the
FUB API.  Used by the CLI ``fub`` command group and the admin-center.
"""

from __future__ import annotations

import json
from typing import Any

from providers.followupboss.client import FubClient
from store.authn import resolve_realtor_bearer
from store.common import integration_auth_error_response, json_response
from store.profile_repo import fub_config_from_profile, load_realtor_profile


# ─────────────────────────────────────────────────────────────────────────────
# Auth helpers
# ─────────────────────────────────────────────────────────────────────────────

def _auth(request) -> tuple[str, FubClient | None, Any]:
    """
    Authenticate the request and return (uid, fub_client, error_response).
    If error_response is not None the caller should return it immediately.
    """
    decoded, err, _token = resolve_realtor_bearer(request)
    if err:
        return "", None, integration_auth_error_response(err)
    uid = decoded["uid"]

    profile, pst = load_realtor_profile(uid)
    if pst not in (200, 404) or not isinstance(profile, dict):
        return uid, None, json_response({"error": "profile_load_failed", "httpStatus": pst}, 503)

    fub = fub_config_from_profile(profile)
    if not fub:
        return uid, None, json_response({"error": "followupboss_not_connected", "hint": "Complete OAuth at /integrations/followupboss/oauth/start"}, 404)

    auth = dict(fub.get("auth") or {})
    client = FubClient(
        access_token_ref=auth.get("accessTokenRef"),
        api_key_ref=auth.get("apiKeyRef"),
        acting_uid=uid,
    )
    return uid, client, None


def _body(request) -> tuple[dict, Any]:
    """Parse JSON body. Returns (dict, error_response)."""
    try:
        raw = request.get_data(as_text=True) or "{}"
        return json.loads(raw), None
    except (json.JSONDecodeError, ValueError) as e:
        return {}, json_response({"error": f"invalid JSON body: {e}"}, 400)


# ─────────────────────────────────────────────────────────────────────────────
# People — list
# ─────────────────────────────────────────────────────────────────────────────

def people_list(request):
    """
    POST /integrations/followupboss/people/list
    Body: { "limit": 50, "offset": 0 }  OR  { "next": "<cursor>" }
    """
    uid, client, err = _auth(request)
    if err:
        return err
    body, err = _body(request)
    if err:
        return err

    limit = min(100, max(1, int(body.get("limit", body.get("batchSize", 50)))))
    next_token = body.get("next") or None
    offset = int(body.get("offset", 0)) if not next_token else None

    resp, st = client.list_people(limit=limit, offset=offset, next_token=next_token)
    return json_response(resp if isinstance(resp, dict) else {}, st)


# ─────────────────────────────────────────────────────────────────────────────
# People — get
# ─────────────────────────────────────────────────────────────────────────────

def people_get(request):
    """
    POST /integrations/followupboss/people/get
    Body: { "personId": 123 }
    """
    _, client, err = _auth(request)
    if err:
        return err
    body, err = _body(request)
    if err:
        return err

    person_id = body.get("personId") or body.get("id")
    if not isinstance(person_id, int) or person_id <= 0:
        return json_response({"error": "personId (positive int) required"}, 400)

    resp, st = client.get_person(person_id)
    return json_response(resp if isinstance(resp, dict) else {}, st)


# ─────────────────────────────────────────────────────────────────────────────
# People — create (upsert by email)
# ─────────────────────────────────────────────────────────────────────────────

def people_create(request):
    """
    POST /integrations/followupboss/people/create
    Body: {
      "firstName": "...", "lastName": "...",
      "emails": [{"value": "..."}],
      "phones": [{"value": "..."}],
      "stage": "New Lead",
      "source": "Referral",
      "tags": [{"name": "tag1"}],
      "price": 1200000
    }
    At minimum firstName OR emails[0] must be provided.
    """
    _, client, err = _auth(request)
    if err:
        return err
    body, err = _body(request)
    if err:
        return err

    first = (body.get("firstName") or "").strip()
    last = (body.get("lastName") or "").strip()
    emails = body.get("emails") or []
    phones = body.get("phones") or []

    if not first and not emails:
        return json_response({"error": "firstName or emails required to create a person"}, 400)

    payload: dict[str, Any] = {}
    if first:
        payload["firstName"] = first
    if last:
        payload["lastName"] = last
    if emails:
        payload["emails"] = [{"value": str(e["value"])} if isinstance(e, dict) else {"value": str(e)} for e in emails[:25]]
    if phones:
        payload["phones"] = [{"value": str(p["value"])} if isinstance(p, dict) else {"value": str(p)} for p in phones[:25]]

    for key in ("stage", "source", "price", "timeframe"):
        if body.get(key) is not None:
            payload[key] = body[key]

    # Tags: accept ["tag1", "tag2"] or [{"name": "tag1"}]
    raw_tags = body.get("tags") or []
    if raw_tags:
        payload["tags"] = [
            t if isinstance(t, dict) and "name" in t else {"name": str(t)}
            for t in raw_tags[:40]
        ]

    resp, st = client.upsert_person(payload)
    return json_response(resp if isinstance(resp, dict) else {}, st)


# ─────────────────────────────────────────────────────────────────────────────
# People — update fields
# ─────────────────────────────────────────────────────────────────────────────

def people_update(request):
    """
    POST /integrations/followupboss/people/update
    Body: { "personId": 123, "firstName": "...", "lastName": "...", ... }
    Only fields present in the body (besides personId) are sent to FUB.
    """
    _, client, err = _auth(request)
    if err:
        return err
    body, err = _body(request)
    if err:
        return err

    person_id = body.get("personId") or body.get("id")
    if not isinstance(person_id, int) or person_id <= 0:
        return json_response({"error": "personId (positive int) required"}, 400)

    payload: dict[str, Any] = {}
    for field in ("firstName", "lastName", "stage", "source", "price", "timeframe", "dealStatus"):
        if body.get(field) is not None:
            payload[field] = body[field]
    if body.get("emails"):
        payload["emails"] = body["emails"]
    if body.get("phones"):
        payload["phones"] = body["phones"]

    if not payload:
        return json_response({"error": "No update fields provided. Supply at least one of: firstName, lastName, stage, source, emails, phones, price"}, 400)

    resp, st = client.update_person(person_id, payload)
    return json_response(resp if isinstance(resp, dict) else {}, st)


# ─────────────────────────────────────────────────────────────────────────────
# People — set stage
# ─────────────────────────────────────────────────────────────────────────────

def people_set_stage(request):
    """
    POST /integrations/followupboss/people/stage
    Body: { "personId": 123, "stage": "Active Buyer" }
    """
    _, client, err = _auth(request)
    if err:
        return err
    body, err = _body(request)
    if err:
        return err

    person_id = body.get("personId") or body.get("id")
    stage = (body.get("stage") or "").strip()
    if not isinstance(person_id, int) or person_id <= 0:
        return json_response({"error": "personId (positive int) required"}, 400)
    if not stage:
        return json_response({"error": "stage (non-empty string) required"}, 400)

    resp, st = client.update_person(person_id, {"stage": stage})
    return json_response(resp if isinstance(resp, dict) else {}, st)


# ─────────────────────────────────────────────────────────────────────────────
# Tags — add
# ─────────────────────────────────────────────────────────────────────────────

def tags_add(request):
    """
    POST /integrations/followupboss/people/tags/add
    Body: { "personId": 123, "tags": ["hot-lead", "cash-buyer"] }
    Reads existing tags then merges (deduplicated) before writing.
    """
    _, client, err = _auth(request)
    if err:
        return err
    body, err = _body(request)
    if err:
        return err

    person_id = body.get("personId") or body.get("id")
    new_tags_raw = body.get("tags") or []
    if not isinstance(person_id, int) or person_id <= 0:
        return json_response({"error": "personId (positive int) required"}, 400)
    if not new_tags_raw:
        return json_response({"error": "tags (non-empty list of strings) required"}, 400)

    new_tags = [str(t).strip().lower() for t in new_tags_raw if str(t).strip()]

    # Fetch current person to get existing tags
    current, cst = client.get_person(person_id)
    if cst >= 400:
        return json_response({"error": "could not fetch person to read tags", "fub_status": cst, "detail": current}, cst)

    existing_tags = current.get("tags") if isinstance(current.get("tags"), list) else []
    existing_names = {str(t.get("name") or "").strip().lower() for t in existing_tags if isinstance(t, dict)}

    merged = list(existing_tags)  # keep original objects for existing
    for nt in new_tags:
        if nt and nt not in existing_names:
            merged.append({"name": nt})
            existing_names.add(nt)

    resp, st = client.update_person(person_id, {"tags": merged})
    return json_response(
        {**(resp if isinstance(resp, dict) else {}), "_tagsAfter": [t.get("name") for t in merged if isinstance(t, dict)]},
        st,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Tags — remove
# ─────────────────────────────────────────────────────────────────────────────

def tags_remove(request):
    """
    POST /integrations/followupboss/people/tags/remove
    Body: { "personId": 123, "tags": ["old-tag"] }
    """
    _, client, err = _auth(request)
    if err:
        return err
    body, err = _body(request)
    if err:
        return err

    person_id = body.get("personId") or body.get("id")
    remove_raw = body.get("tags") or []
    if not isinstance(person_id, int) or person_id <= 0:
        return json_response({"error": "personId (positive int) required"}, 400)
    if not remove_raw:
        return json_response({"error": "tags (non-empty list of strings) required"}, 400)

    remove_set = {str(t).strip().lower() for t in remove_raw if str(t).strip()}

    current, cst = client.get_person(person_id)
    if cst >= 400:
        return json_response({"error": "could not fetch person to read tags", "fub_status": cst, "detail": current}, cst)

    existing_tags = current.get("tags") if isinstance(current.get("tags"), list) else []
    filtered = [t for t in existing_tags if isinstance(t, dict) and str(t.get("name") or "").strip().lower() not in remove_set]

    resp, st = client.update_person(person_id, {"tags": filtered})
    return json_response(
        {**(resp if isinstance(resp, dict) else {}), "_tagsAfter": [t.get("name") for t in filtered if isinstance(t, dict)]},
        st,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Notes — create
# ─────────────────────────────────────────────────────────────────────────────

def notes_create(request):
    """
    POST /integrations/followupboss/notes/create
    Body: { "personId": 123, "body": "Called — very interested." }
    """
    _, client, err = _auth(request)
    if err:
        return err
    body, err = _body(request)
    if err:
        return err

    person_id = body.get("personId") or body.get("id")
    note_body = (body.get("body") or "").strip()
    if not isinstance(person_id, int) or person_id <= 0:
        return json_response({"error": "personId (positive int) required"}, 400)
    if not note_body:
        return json_response({"error": "body (non-empty string) required"}, 400)

    resp, st = client.create_note(person_id, note_body)
    return json_response(resp if isinstance(resp, dict) else {}, st)


# ─────────────────────────────────────────────────────────────────────────────
# Tasks — create
# ─────────────────────────────────────────────────────────────────────────────

def tasks_create(request):
    """
    POST /integrations/followupboss/tasks/create
    Body: { "personId": 123, "body": "Follow up on listing interest by Friday." }
    """
    _, client, err = _auth(request)
    if err:
        return err
    body, err = _body(request)
    if err:
        return err

    person_id = body.get("personId") or body.get("id")
    task_body = (body.get("body") or "").strip()
    if not isinstance(person_id, int) or person_id <= 0:
        return json_response({"error": "personId (positive int) required"}, 400)
    if not task_body:
        return json_response({"error": "body (non-empty string) required"}, 400)

    resp, st = client.create_task(person_id, task_body)
    return json_response(resp if isinstance(resp, dict) else {}, st)


# ─────────────────────────────────────────────────────────────────────────────
# Import — trigger migration.import_leads_v1 (sync all people from FUB → Firestore)
# ─────────────────────────────────────────────────────────────────────────────

def trigger_import(request):
    """
    POST /integrations/followupboss/import
    Body: { "personId": 123 }  — single refresh, OR
    Body: {}                   — full sync (all FUB people)
    Body: { "maxPages": 5 }    — partial sync

    This is a convenience wrapper; actual execution happens via the core runner.
    """
    uid, _, err = _auth(request)
    if err:
        return err
    body, err = _body(request)
    if err:
        return err

    from dispatcher.core_client import send_state_to_core
    import uuid as _uuid

    person_id = body.get("personId") or body.get("id")
    max_pages = body.get("maxPages")

    wf_payload: dict = {}
    if isinstance(person_id, int) and person_id > 0:
        wf_payload["personId"] = person_id
    if isinstance(max_pages, int) and max_pages > 0:
        wf_payload["maxListPages"] = max_pages

    state = {
        "state_version": 1,
        "correlation_id": f"cli_import_{_uuid.uuid4().hex[:12]}",
        "source": {"provider": "followupboss", "event_type": "manual_import"},
        "user_id": uid,
        "payload": wf_payload,
        "metadata": {"execution_policy": {"volatile_external_allowed": False, "integration_maintenance_allowed": True}},
    }

    try:
        resp, st = send_state_to_core(state, workflow_id="migration.import_leads_v1", timeout=120)
    except Exception as e:
        return json_response({"error": f"core run failed: {e}"}, 502)

    return json_response(resp if isinstance(resp, dict) else {}, st)

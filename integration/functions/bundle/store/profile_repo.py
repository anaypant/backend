from typing import Any

from store.common import db_origin, post_json_platform


def delete_followupboss_event_ledger_for_uid(uid: str) -> tuple[int, dict | None]:
    """
    Best-effort: delete IntegrationEventLedger docs for this realtor's Follow Up Boss ingress.
    Queries by ownerUid (required for non-admin query authz), filters provider in-process.
    """
    deleted = 0
    page_token: str | None = None
    while True:
        body: dict = {
            "path": "IntegrationEventLedger",
            "filters": [{"field": "ownerUid", "op": "==", "value": uid}],
            "limit": 100,
        }
        if page_token:
            body["pageToken"] = page_token
        resp, st = post_json_platform(db_origin() + "/db/query/", body, acting_uid=uid)
        if st >= 400:
            return deleted, {"httpStatus": st, "detail": resp}
        items = resp.get("items") or []
        for it in items:
            if not isinstance(it, dict):
                continue
            data = it.get("data") if isinstance(it.get("data"), dict) else {}
            if data.get("provider") != "followupboss":
                continue
            path = it.get("path")
            if not isinstance(path, str) or not path.strip():
                continue
            _d, dst = post_json_platform(db_origin() + "/db/delete/", {"path": path}, acting_uid=uid)
            if dst < 400:
                deleted += 1
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return deleted, None


def fub_config_from_profile(doc_data: dict) -> dict | None:
    integrations = doc_data.get("integrations")
    if not isinstance(integrations, dict):
        return None
    fub = integrations.get("followupboss")
    return fub if isinstance(fub, dict) else None


def load_realtor_profile(uid: str) -> tuple[dict, int]:
    doc_path = f"Realtors/{uid}"
    body, status = post_json_platform(
        db_origin() + "/db/read/",
        {"path": doc_path},
        acting_uid=uid,
    )
    if status == 200 and isinstance(body.get("data"), dict):
        return body["data"], 200
    if status == 404:
        return {}, 404
    return {"error": "db read failed", "detail": body}, status


def save_fub_profile(uid: str, fub_profile: dict) -> tuple[dict, int]:
    existing, status = load_realtor_profile(uid)
    if status not in (200, 404):
        return existing, status
    integrations = dict(existing.get("integrations") or {})
    integrations["followupboss"] = fub_profile
    payload = {"path": f"Realtors/{uid}", "data": {"integrations": integrations}, "merge": True}
    return post_json_platform(
        db_origin() + "/db/upsert/",
        payload,
        acting_uid=uid,
    )


def load_fub_profile_by_connection_id(connection_id: str) -> tuple[dict | None, dict | None]:
    body, status = post_json_platform(
        db_origin() + "/db/read/",
        {"path": f"Realtors/{connection_id}"},
        acting_uid=connection_id,
    )
    if status == 200 and isinstance(body.get("data"), dict):
        profile = body["data"]
        return profile, fub_config_from_profile(profile)
    if status == 404:
        return None, None
    return None, None


def save_fub_profile_by_connection_id(connection_id: str, fub_profile: dict):
    body, status = post_json_platform(
        db_origin() + "/db/read/",
        {"path": f"Realtors/{connection_id}"},
        acting_uid=connection_id,
    )
    existing: dict = {}
    if status == 200 and isinstance(body.get("data"), dict):
        existing = body["data"]
    elif status != 404:
        return

    integrations = dict(existing.get("integrations") or {})
    integrations["followupboss"] = fub_profile
    post_json_platform(
        db_origin() + "/db/upsert/",
        {"path": f"Realtors/{connection_id}", "data": {"integrations": integrations}, "merge": True},
        acting_uid=connection_id,
    )


def put_event_ledger(connection_id: str, event_id: str, event: dict) -> tuple[bool, dict]:
    """Returns (inserted, record)."""
    key = f"followupboss::{connection_id}::{event_id}"
    path = f"IntegrationEventLedger/{key}"
    body, status = post_json_platform(
        db_origin() + "/db/read/",
        {"path": path},
        acting_uid=connection_id,
    )
    if status == 200 and isinstance(body.get("data"), dict):
        data: dict[str, Any] = body["data"]
        return False, data
    if status != 404:
        return False, {"error": "ledger read failed", "detail": body, "httpStatus": status}

    record = {
        "provider": "followupboss",
        "connectionId": connection_id,
        "eventId": event_id,
        "eventType": event.get("event"),
        "status": "received",
        "raw": event,
        "ownerUid": connection_id,
        "createdBy": connection_id,
    }
    _, ust = post_json_platform(
        db_origin() + "/db/upsert/",
        {"path": path, "data": record, "merge": True},
        acting_uid=connection_id,
    )
    if ust >= 400:
        return False, {"error": "ledger upsert failed", "httpStatus": ust}
    return True, record


def update_event_status(connection_id: str, event_id: str, status: str, detail: dict | None = None):
    key = f"followupboss::{connection_id}::{event_id}"
    path = f"IntegrationEventLedger/{key}"
    data: dict[str, Any] = {"status": status}
    if detail is not None:
        data["detail"] = detail
    post_json_platform(
        db_origin() + "/db/upsert/",
        {"path": path, "data": data, "merge": True},
        acting_uid=connection_id,
    )

from typing import Any

from store.authn import ensure_firebase
from store.common import db_origin, post_json


def fub_config_from_profile(doc_data: dict) -> dict | None:
    integrations = doc_data.get("integrations")
    if not isinstance(integrations, dict):
        return None
    fub = integrations.get("followupboss")
    return fub if isinstance(fub, dict) else None


def load_realtor_profile(uid: str, user_jwt: str) -> tuple[dict, int]:
    doc_path = f"Realtors/{uid}"
    body, status = post_json(db_origin() + "/db/read/", {"path": doc_path}, user_jwt=user_jwt)
    if status == 200 and isinstance(body.get("data"), dict):
        return body["data"], 200
    if status == 404:
        return {}, 404
    return {"error": "db read failed", "detail": body}, status


def save_fub_profile(uid: str, user_jwt: str, fub_profile: dict) -> tuple[dict, int]:
    existing, status = load_realtor_profile(uid, user_jwt)
    if status not in (200, 404):
        return existing, status
    integrations = dict(existing.get("integrations") or {})
    integrations["followupboss"] = fub_profile
    payload = {"path": f"Realtors/{uid}", "data": {"integrations": integrations}, "merge": True}
    return post_json(db_origin() + "/db/upsert/", payload, user_jwt=user_jwt)


def load_fub_profile_by_connection_id(connection_id: str) -> tuple[dict | None, dict | None]:
    # TODO: Replace with DB internal API call authenticated as service account.
    ensure_firebase()
    from firebase_admin import firestore

    snap = firestore.client().collection("Realtors").document(connection_id).get()
    if not snap.exists:
        return None, None
    profile = snap.to_dict() or {}
    return profile, fub_config_from_profile(profile)


def save_fub_profile_by_connection_id(connection_id: str, fub_profile: dict):
    # TODO: Replace with DB internal API call authenticated as service account.
    ensure_firebase()
    from firebase_admin import firestore

    firestore.client().collection("Realtors").document(connection_id).set(
        {"integrations": {"followupboss": fub_profile}},
        merge=True,
    )


def put_event_ledger(connection_id: str, event_id: str, event: dict) -> tuple[bool, dict]:
    """Returns (inserted, record)."""
    ensure_firebase()
    from firebase_admin import firestore

    key = f"followupboss::{connection_id}::{event_id}"
    ref = firestore.client().collection("IntegrationEventLedger").document(key)
    snap = ref.get()
    if snap.exists:
        data: dict[str, Any] = snap.to_dict() or {}
        return False, data

    record = {
        "provider": "followupboss",
        "connectionId": connection_id,
        "eventId": event_id,
        "eventType": event.get("event"),
        "status": "received",
        "raw": event,
    }
    ref.set(record, merge=True)
    return True, record


def update_event_status(connection_id: str, event_id: str, status: str, detail: dict | None = None):
    ensure_firebase()
    from firebase_admin import firestore

    key = f"followupboss::{connection_id}::{event_id}"
    ref = firestore.client().collection("IntegrationEventLedger").document(key)
    payload = {"status": status}
    if detail is not None:
        payload["detail"] = detail
    ref.set(payload, merge=True)

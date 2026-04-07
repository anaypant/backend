# UPSERT function for database (create or merge-update)

import json

import firebase_admin
import functions_framework
from firebase_admin import auth, firestore


def _json_response(payload: dict, status: int):
    return (json.dumps(payload), status, {"Content-Type": "application/json"})


def _ensure_firebase():
    if not firebase_admin._apps:
        firebase_admin.initialize_app()


def _bearer_token(request) -> str | None:
    header = request.headers.get("Authorization") or ""
    parts = header.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip() or None
    return None


def _is_admin(decoded: dict) -> bool:
    if decoded.get("admin") is True:
        return True
    role = decoded.get("role")
    return role == "admin"


def _caller_owns_document(decoded: dict, doc_data: dict | None) -> bool:
    if not doc_data:
        return False
    uid = decoded["uid"]
    owner = doc_data.get("ownerUid") or doc_data.get("createdBy")
    return owner == uid


def _caller_may_update_existing(decoded: dict, existing: dict) -> bool:
    return _is_admin(decoded) or _caller_owns_document(decoded, existing)


def _caller_may_create(decoded: dict, data: dict) -> bool:
    if _is_admin(decoded):
        return True
    uid = decoded["uid"]
    owner_uid = data.get("ownerUid", uid)
    created_by = data.get("createdBy", uid)
    return owner_uid == uid and created_by == uid


def _strip_invalid_owner_changes(decoded: dict, patch: dict) -> dict | None:
    """Non-admins cannot set ownerUid/createdBy to another user. Returns None if forbidden."""
    if _is_admin(decoded):
        return dict(patch)
    uid = decoded["uid"]
    out = dict(patch)
    for key in ("ownerUid", "createdBy"):
        if key in out and out[key] != uid:
            return None
    return out


def _prepare_write_for_create(decoded: dict, data: dict) -> dict:
    uid = decoded["uid"]
    out = dict(data)
    if not _is_admin(decoded):
        out.setdefault("ownerUid", uid)
        out.setdefault("createdBy", uid)
    return out


def _document_ref_from_path(db, path: str):
    trimmed = path.strip()
    if not trimmed:
        raise ValueError("path is empty")
    parts = [p for p in trimmed.split("/") if p]
    if len(parts) < 2:
        raise ValueError("path needs at least collection/document")
    if len(parts) % 2 != 0:
        raise ValueError("path must end on a document id (even number of segments)")
    ref = db.collection(parts[0]).document(parts[1])
    for i in range(2, len(parts), 2):
        ref = ref.collection(parts[i]).document(parts[i + 1])
    return ref


@functions_framework.http
def main(request):
    """
    Creates or updates (merge) a Firestore document.

    Headers:
        Authorization: Bearer <Firebase ID token>

    JSON body:
        path (str): slash-separated path to the document (same as read/delete).
        data (object): fields to write. For merge updates, shallow-merged with existing data.
        merge (bool, optional): passed to Firestore set(); default true (upsert / partial update).

    Authorization:
        - Document does not exist: admin, or payload ownerUid/createdBy (when present) must
          both equal the caller uid; missing owner fields default to caller on write.
        - Document exists: admin, or existing ownerUid/createdBy matches caller uid.
        - Non-admins cannot change ownerUid/createdBy to another uid on update.
    """

    _ensure_firebase()

    token = _bearer_token(request)
    if not token:
        return _json_response({"error": "missing Authorization bearer token"}, 401)

    try:
        decoded = auth.verify_id_token(token, check_revoked=True)
    except auth.RevokedIdTokenError:
        return _json_response({"error": "token revoked"}, 401)
    except auth.ExpiredIdTokenError:
        return _json_response({"error": "token expired"}, 401)
    except auth.InvalidIdTokenError:
        return _json_response({"error": "invalid token"}, 401)
    except auth.CertificateFetchError:
        return _json_response({"error": "auth verification unavailable"}, 503)

    try:
        request_body = request.get_json(silent=True) or {}
        doc_path = request_body.get("path")
        data = request_body.get("data")
        merge = request_body.get("merge", True)
    except Exception:
        return _json_response({"error": "invalid JSON body"}, 400)

    if not doc_path or not isinstance(doc_path, str):
        return _json_response(
            {"error": "path is required and must be a string"},
            400,
        )
    if data is None or not isinstance(data, dict):
        return _json_response(
            {"error": "data is required and must be a JSON object"},
            400,
        )
    if not isinstance(merge, bool):
        return _json_response({"error": "merge must be a boolean when provided"}, 400)

    db = firestore.client()
    try:
        doc_ref = _document_ref_from_path(db, doc_path)
    except ValueError as e:
        return _json_response({"error": str(e)}, 400)

    snap = doc_ref.get()
    existing_dict = snap.to_dict() if snap.exists else None

    if snap.exists:
        if not _caller_may_update_existing(decoded, existing_dict):
            return _json_response({"error": "forbidden"}, 403)
        patch = _strip_invalid_owner_changes(decoded, data)
        if patch is None:
            return _json_response(
                {"error": "forbidden: cannot reassign ownerUid or createdBy"},
                403,
            )
        write_payload = patch
        created = False
    else:
        if not _caller_may_create(decoded, data):
            return _json_response({"error": "forbidden"}, 403)
        write_payload = _prepare_write_for_create(decoded, data)
        created = True

    # Full replace (merge=false) would drop ownership fields; keep them for non-admins.
    if snap.exists and not merge and not _is_admin(decoded) and existing_dict:
        write_payload = dict(write_payload)
        for key in ("ownerUid", "createdBy"):
            if key in existing_dict:
                write_payload[key] = existing_dict[key]

    doc_ref.set(write_payload, merge=merge)

    return _json_response(
        {
            "path": doc_ref.path,
            "id": doc_ref.id,
            "created": created,
        },
        200,
    )

# READ function for database

import acs_internal as acs

import datetime
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
    for h in (acs.USER_JWT_HEADER, "Authorization"):
        raw = request.headers.get(h) or ""
        parts = raw.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            t = parts[1].strip()
            if t:
                return t
    return None


def _is_admin(decoded: dict) -> bool:
    if decoded.get("admin") is True:
        return True
    role = decoded.get("role")
    return role == "admin"


def _caller_may_read(decoded: dict, doc_data: dict | None) -> bool:
    if _is_admin(decoded):
        return True
    if not doc_data:
        return False
    uid = decoded["uid"]
    owner = doc_data.get("ownerUid") or doc_data.get("createdBy")
    return owner == uid


def _document_ref_from_path(db, path: str):
    """
    Build a DocumentReference from a slash-separated path: collection/doc[/collection/doc]...
    Root is a collection id; the leaf is always a document id.
    """
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


def _sanitize_for_json(obj):
    if obj is None:
        return None
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_for_json(v) for v in obj]
    if isinstance(obj, datetime.datetime):
        return obj.isoformat()
    if hasattr(obj, "latitude") and hasattr(obj, "longitude"):
        return {"latitude": obj.latitude, "longitude": obj.longitude}
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if hasattr(obj, "path") and hasattr(obj, "id"):
        return obj.path
    return str(obj)


@functions_framework.http
def main(request):
    """
    Returns a Firestore document as JSON after authz.

    Headers:
        Authorization: Bearer <Firebase ID token>

    JSON body:
        path (str): slash-separated path from root collection to leaf document, e.g.
            "People/abc" or "Organizations/org1/Realtors/r1"

    Authorization:
        - Firebase custom claim admin: true, or role == "admin", or
        - Document field ownerUid or createdBy equals the token uid.

    Response 200:
        {"path": "...", "id": "...", "data": { ... }}
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
    except Exception:
        return _json_response({"error": "invalid JSON body"}, 400)

    if not doc_path or not isinstance(doc_path, str):
        return _json_response(
            {"error": "path is required and must be a string"},
            400,
        )

    db = firestore.client()
    try:
        doc_ref = _document_ref_from_path(db, doc_path)
    except ValueError as e:
        return _json_response({"error": str(e)}, 400)

    snap = doc_ref.get()
    if not snap.exists:
        return _json_response({"error": "not found"}, 404)

    data = snap.to_dict()
    if not _caller_may_read(decoded, data):
        return _json_response({"error": "forbidden"}, 403)

    payload = {
        "path": snap.reference.path,
        "id": snap.id,
        "data": _sanitize_for_json(data),
    }
    return _json_response(payload, 200)

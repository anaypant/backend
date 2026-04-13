# QUERY function — list documents in a Firestore collection with filters / order / pagination.

import acs_internal as acs

import datetime
import json
import os
import re

import firebase_admin
import functions_framework
from firebase_admin import auth, firestore
from google.cloud.firestore import Query as FsQuery


_MAX_LIMIT = 100
_DEFAULT_LIMIT = 25
_FIELD_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)*$")
_ALLOWED_OPS = frozenset(
    {
        "==",
        "!=",
        "<",
        "<=",
        ">",
        ">=",
        "in",
        "array-contains",
        "array-contains-any",
    }
)


def _json_response(payload: dict, status: int):
    return (json.dumps(payload), status, {"Content-Type": "application/json"})


def _ensure_firebase():
    if not firebase_admin._apps:
        pid = (os.environ.get("GCLOUD_PROJECT") or os.environ.get("GCP_PROJECT") or "").strip()
        if pid:
            firebase_admin.initialize_app(options={"projectId": pid})
        else:
            firebase_admin.initialize_app()


def _decode_firebase_from_request(request):
    ep = acs.decode_endpoint_user_info_claims(request)
    if ep:
        uid = ep.get("user_id") or ep.get("sub")
        if not isinstance(uid, str) or not uid:
            return None, "invalid gateway identity"
        return {**ep, "uid": uid}, None
    last_inv: str | None = None
    for h in acs.END_USER_BEARER_HEADER_ORDER:
        token = acs.parse_bearer_header(request, h)
        if not token:
            continue
        try:
            return auth.verify_id_token(token, check_revoked=True), None
        except auth.RevokedIdTokenError:
            return None, "token revoked"
        except auth.ExpiredIdTokenError:
            return None, "token expired"
        except auth.InvalidIdTokenError:
            last_inv = "invalid token"
            continue
        except auth.CertificateFetchError:
            return None, "auth verification unavailable"
    return None, last_inv or "missing user credentials"


def _is_admin(decoded: dict) -> bool:
    if decoded.get("admin") is True:
        return True
    role = decoded.get("role")
    return role == "admin"


def _collection_ref_from_path(db, path: str):
    """
    Path to a collection: odd number of segments, last segment is the collection id.
    Examples: "People" -> top-level; "Organizations/org1/Realtors" -> subcollection Realtors.
    """
    trimmed = path.strip()
    if not trimmed:
        raise ValueError("path is empty")
    parts = [p for p in trimmed.split("/") if p]
    if not parts:
        raise ValueError("path is empty")
    if len(parts) % 2 == 0:
        raise ValueError("path must end on a collection (odd number of segments)")
    if len(parts) == 1:
        return db.collection(parts[0])
    ref = db.collection(parts[0]).document(parts[1])
    i = 2
    while i < len(parts) - 1:
        ref = ref.collection(parts[i]).document(parts[i + 1])
        i += 2
    return ref.collection(parts[-1])


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


def _normalize_op(op: str) -> str | None:
    if not isinstance(op, str):
        return None
    key = op.strip()
    if key == "array-contains":
        return "array_contains"
    if key == "array-contains-any":
        return "array_contains_any"
    if key in _ALLOWED_OPS:
        return key
    return None


def _validate_field(name: str) -> bool:
    return isinstance(name, str) and bool(_FIELD_RE.match(name))


def _ownership_ok_for_non_admin(filters: list, uid: str) -> bool:
    has_self_owner = False
    for f in filters:
        if not isinstance(f, dict):
            continue
        field = f.get("field")
        op = f.get("op")
        val = f.get("value")
        if field not in ("ownerUid", "createdBy"):
            continue
        if op != "==":
            continue
        if val == uid:
            has_self_owner = True
        else:
            return False
    return has_self_owner


def _forbidden_owner_filters(filters: list, uid: str) -> bool:
    for f in filters:
        if not isinstance(f, dict):
            continue
        field = f.get("field")
        op = f.get("op")
        val = f.get("value")
        if field in ("ownerUid", "createdBy") and op == "==" and val != uid:
            return True
    return False


@functions_framework.http
def main(request):
    """
    Query documents in a collection (Firestore Query).

    Headers:
        Authorization: Bearer <Firebase ID token>

    JSON body:
        path (str): collection path (odd segments), e.g. "People" or "Organizations/org1/Realtors"
        filters (list, optional): { "field", "op", "value } — op one of
            ==, !=, <, <=, >, >=, in, array-contains, array-contains-any
        orderBy (list, optional): { "field", "direction": "ASC"|"DESC" }
        limit (int, optional): default 25, max 100
        pageToken (str, optional): document path of the last doc from the previous page
            (same format as read path, e.g. "People/abc")
        collectionGroup (bool, optional): if true, path must be a single collection id; admin only

    Non-admins must include ownerUid == <uid> or createdBy == <uid> (== only) among filters.

    Response 200:
        { "items": [ { "path", "id", "data" }, ... ], "nextPageToken": "..." | null }
    """

    _ensure_firebase()

    decoded, verr = _decode_firebase_from_request(request)
    if verr:
        st = 503 if verr == "auth verification unavailable" else 401
        return _json_response({"error": verr}, st)

    uid = decoded["uid"]

    try:
        body = request.get_json(silent=True) or {}
        col_path = body.get("path")
        filters = body.get("filters") or []
        order_by = body.get("orderBy") or []
        limit = body.get("limit", _DEFAULT_LIMIT)
        page_token = body.get("pageToken")
        collection_group = bool(body.get("collectionGroup", False))
    except Exception:
        return _json_response({"error": "invalid JSON body"}, 400)

    if not col_path or not isinstance(col_path, str):
        return _json_response(
            {"error": "path is required and must be a string"},
            400,
        )
    if not isinstance(filters, list):
        return _json_response({"error": "filters must be a list"}, 400)
    if not isinstance(order_by, list):
        return _json_response({"error": "orderBy must be a list"}, 400)
    if not isinstance(limit, int) or limit < 1:
        return _json_response({"error": "limit must be a positive integer"}, 400)
    limit = min(limit, _MAX_LIMIT)
    if page_token is not None and (not isinstance(page_token, str) or not page_token.strip()):
        return _json_response({"error": "pageToken must be a non-empty string when set"}, 400)

    if collection_group:
        if not _is_admin(decoded):
            return _json_response({"error": "forbidden: collectionGroup requires admin"}, 403)
        parts = [p for p in col_path.strip().split("/") if p]
        if len(parts) != 1:
            return _json_response(
                {"error": "collectionGroup path must be a single collection id"},
                400,
            )
        db = firestore.client()
        query = db.collection_group(parts[0])
    else:
        db = firestore.client()
        try:
            coll = _collection_ref_from_path(db, col_path)
        except ValueError as e:
            return _json_response({"error": str(e)}, 400)
        query = coll

    if not _is_admin(decoded):
        if _forbidden_owner_filters(filters, uid):
            return _json_response({"error": "forbidden"}, 403)
        if not _ownership_ok_for_non_admin(filters, uid):
            return _json_response(
                {
                    "error": "forbidden: include filter ownerUid or createdBy == your uid",
                },
                403,
            )

    for f in filters:
        if not isinstance(f, dict):
            return _json_response({"error": "each filter must be an object"}, 400)
        field = f.get("field")
        op_raw = f.get("op")
        value = f.get("value")
        if not _validate_field(field):
            return _json_response({"error": f"invalid filter field: {field!r}"}, 400)
        op = _normalize_op(op_raw)
        if op is None:
            return _json_response({"error": f"unsupported filter op: {op_raw!r}"}, 400)
        try:
            query = query.where(field, op, value)
        except Exception as e:
            return _json_response({"error": f"invalid query: {e!s}"}, 400)

    for clause in order_by:
        if not isinstance(clause, dict):
            return _json_response({"error": "each orderBy entry must be an object"}, 400)
        field = clause.get("field")
        direction = (clause.get("direction") or "ASC").upper()
        if not _validate_field(field):
            return _json_response({"error": f"invalid orderBy field: {field!r}"}, 400)
        if direction not in ("ASC", "DESC"):
            return _json_response({"error": "orderBy direction must be ASC or DESC"}, 400)
        dir_enum = (
            FsQuery.DESCENDING if direction == "DESC" else FsQuery.ASCENDING
        )
        try:
            query = query.order_by(field, direction=dir_enum)
        except Exception as e:
            return _json_response({"error": f"invalid orderBy: {e!s}"}, 400)

    if page_token:
        try:
            cursor_snap = db.document(page_token.strip()).get()
        except Exception:
            return _json_response({"error": "invalid pageToken path"}, 400)
        if not cursor_snap.exists:
            return _json_response({"error": "pageToken document not found"}, 400)
        try:
            query = query.start_after(cursor_snap)
        except Exception as e:
            return _json_response({"error": f"invalid pagination: {e!s}"}, 400)

    fetch_limit = limit + 1
    try:
        snaps = list(query.limit(fetch_limit).stream())
    except Exception as e:
        return _json_response(
            {"error": f"query failed (missing index?): {e!s}"},
            400,
        )

    has_more = len(snaps) > limit
    page = snaps[:limit]
    items = []
    for snap in page:
        items.append(
            {
                "path": snap.reference.path,
                "id": snap.id,
                "data": _sanitize_for_json(snap.to_dict()),
            }
        )

    next_token = None
    if has_more and page:
        next_token = page[-1].reference.path

    return _json_response(
        {"items": items, "nextPageToken": next_token},
        200,
    )

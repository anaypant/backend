import os

import firebase_admin
from firebase_admin import auth

import acs_internal as acs


def ensure_firebase():
    if not firebase_admin._apps:
        pid = (os.environ.get("GCLOUD_PROJECT") or os.environ.get("GCP_PROJECT") or "").strip()
        if pid:
            firebase_admin.initialize_app(options={"projectId": pid})
        else:
            firebase_admin.initialize_app()


def verify_realtor(id_token: str) -> tuple[dict | None, str | None]:
    ensure_firebase()
    try:
        decoded = auth.verify_id_token(id_token, check_revoked=True)
    except auth.InvalidIdTokenError:
        return None, "invalid token"
    except auth.ExpiredIdTokenError:
        return None, "token expired"
    except auth.RevokedIdTokenError:
        return None, "token revoked"
    if decoded.get("role") != "realtor":
        return None, "forbidden"
    return decoded, None


def resolve_realtor_bearer(request) -> tuple[dict | None, str | None, str | None]:
    """
    Identity: (1) ESP-validated Firebase claims in X-Endpoint-API-UserInfo (public gateway), or
    (2) verify Bearer tokens in END_USER_BEARER_HEADER_ORDER (see acs_internal).

    Public clients send Authorization: Bearer <Firebase>. Internal hops may use the same pattern with
    X-GCP-Identity for Google OIDC (see acs_internal).

    Returns (decoded_claims, error, id_token) — id_token set only for path (2).

    Tracing HTTP 401 on integration routes (e.g. GET /integrations/followupboss/oauth/start):
    - error "missing bearer token": no usable Bearer in the headers above and no gateway userinfo.
    - "invalid token" / "token expired" / "token revoked": Firebase verify_id_token failed.
    - "forbidden": token valid but custom claim role is not "realtor".
    - "invalid gateway identity": gateway headers present but incomplete or wrong role.

    A separate 401 with phase "db_read" comes from the internal DB gateway (acting_uid / platform auth),
    not from this function.
    """
    claims = acs.decode_endpoint_user_info_claims(request)
    if claims:
        uid = claims.get("user_id") or claims.get("sub")
        if not isinstance(uid, str) or not uid:
            return None, "invalid gateway identity", None
        if claims.get("role") != "realtor":
            return None, "forbidden", None
        return {**claims, "uid": uid}, None, None

    last_inv: str | None = None
    for h in acs.END_USER_BEARER_HEADER_ORDER:
        token = acs.parse_bearer_header(request, h)
        if not token:
            continue
        decoded, err = verify_realtor(token)
        if decoded is not None:
            return decoded, None, token
        if err in ("forbidden", "token expired", "token revoked"):
            return None, err, None
        last_inv = err or "invalid token"
    return None, last_inv or "missing bearer token", None

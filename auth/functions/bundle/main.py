"""Auth Cloud Functions: realtor/internal signup and login (password + Google via Identity Toolkit REST).

Profile writes go to the internal DB gateway: ``Authorization`` carries the Google OIDC token;
``X-ACS-Application-Authorization`` carries the Firebase ID token (see docs/acs-internal-request-contract.md).
"""

from __future__ import annotations

import datetime
import json
import os
import urllib.error
import urllib.parse
import urllib.request

from google.auth.transport.requests import Request
from google.oauth2 import id_token as oauth_id_token

import acs_internal as acs
import firebase_admin
import firestore_profile as fp
import functions_framework
from firebase_admin import auth
from firebase_admin import exceptions as fb_exc


def _json_response(payload: dict, status: int):
    return (json.dumps(payload), status, {"Content-Type": "application/json"})


def _ensure_firebase():
    if not firebase_admin._apps:
        firebase_admin.initialize_app()


def _api_key() -> str | None:
    k = (os.environ.get("FIREBASE_WEB_API_KEY") or "").strip()
    return k or None


def _require_api_key():
    k = _api_key()
    if not k:
        raise RuntimeError("FIREBASE_WEB_API_KEY is not set")
    return k


def _post_json(url: str, payload: dict) -> tuple[dict, int]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            raw = resp.read().decode("utf-8")
            return (json.loads(raw) if raw else {}), resp.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            return json.loads(raw), e.code
        except json.JSONDecodeError:
            return {"error": {"message": raw, "code": e.code}}, e.code


def _post_form(url: str, form: dict) -> tuple[dict, int]:
    data = urllib.parse.urlencode(form).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            raw = resp.read().decode("utf-8")
            return (json.loads(raw) if raw else {}), resp.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            return json.loads(raw), e.code
        except json.JSONDecodeError:
            return {"error": {"message": raw, "code": e.code}}, e.code


def _sign_in_password(email: str, password: str) -> tuple[dict, int]:
    key = _require_api_key()
    url = (
        "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword"
        f"?key={urllib.parse.quote(key)}"
    )
    return _post_json(
        url,
        {
            "email": email,
            "password": password,
            "returnSecureToken": True,
        },
    )


def _sign_in_google_id_token(google_id_token: str) -> tuple[dict, int]:
    key = _require_api_key()
    url = (
        "https://identitytoolkit.googleapis.com/v1/accounts:signInWithIdp"
        f"?key={urllib.parse.quote(key)}"
    )
    post_body = urllib.parse.urlencode(
        {"id_token": google_id_token, "providerId": "google.com"}
    )
    return _post_json(
        url,
        {
            "requestUri": "https://localhost",
            "postBody": post_body,
            "returnIdpCredential": True,
            "returnSecureToken": True,
        },
    )


def _refresh_tokens(refresh_token: str) -> tuple[dict, int]:
    key = _require_api_key()
    url = f"https://securetoken.googleapis.com/v1/token?key={urllib.parse.quote(key)}"
    return _post_form(
        url,
        {"grant_type": "refresh_token", "refresh_token": refresh_token},
    )


def _normalize_token_bundle(
    firebase_rest: dict, refreshed: dict | None = None
) -> dict:
    """Shape a client-friendly token payload (camelCase)."""
    out = {
        "idToken": firebase_rest.get("idToken"),
        "refreshToken": firebase_rest.get("refreshToken"),
        "expiresIn": firebase_rest.get("expiresIn"),
        "localId": firebase_rest.get("localId"),
        "email": firebase_rest.get("email"),
        "displayName": firebase_rest.get("displayName"),
        "photoUrl": firebase_rest.get("photoUrl"),
    }
    if refreshed:
        out["idToken"] = refreshed.get("id_token") or out["idToken"]
        out["refreshToken"] = refreshed.get("refresh_token") or out["refreshToken"]
        out["expiresIn"] = str(refreshed.get("expires_in", "")) or out["expiresIn"]
        out["localId"] = refreshed.get("user_id") or out["localId"]
    return {k: v for k, v in out.items() if v is not None}


def _db_internal_origin() -> str:
    host = (os.environ.get("DB_INTERNAL_GATEWAY_HOSTNAME") or "").strip()
    if not host:
        raise RuntimeError("DB_INTERNAL_GATEWAY_HOSTNAME is not set")
    return f"https://{host.rstrip('/')}"


def _post_db(user_jwt: str, path: str, payload: dict) -> tuple[dict, int]:
    """POST internal DB gateway: OIDC on Authorization; app JWT on X-ACS-Application-Authorization."""
    host = (os.environ.get("DB_INTERNAL_GATEWAY_HOSTNAME") or "").strip().rstrip("/")
    audience = f"https://{host}"
    infra = oauth_id_token.fetch_id_token(Request(), audience)
    url = _db_internal_origin() + path
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {infra}",
            acs.APPLICATION_AUTHORIZATION_HEADER: f"Bearer {user_jwt}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            raw = resp.read().decode("utf-8")
            return (json.loads(raw) if raw else {}), resp.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            return json.loads(raw), e.code
        except json.JSONDecodeError:
            return {"error": raw or "upstream error"}, e.code


def _db_upsert(id_token: str, path: str, data: dict, merge: bool = True) -> tuple[dict, int]:
    return _post_db(id_token, "/db/upsert/", {"path": path, "data": data, "merge": merge})


def _sync_profile_signup(id_token: str, uid: str, email: str | None, role: str) -> tuple[dict | None, int]:
    doc = f"{fp.collection_for_role(role)}/{uid}"
    return _db_upsert(
        id_token,
        doc,
        {"uid": uid, "email": (email or "").strip()},
        merge=True,
    )


def _sync_profile_login(id_token: str, uid: str, email: str | None, role: str) -> tuple[dict | None, int]:
    doc = f"{fp.collection_for_role(role)}/{uid}"
    data = {
        "email": (email or "").strip(),
        "lastSignInAt": datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat(),
    }
    return _db_upsert(id_token, doc, data, merge=True)


def _set_role_claim(uid: str, role: str):
    auth.set_custom_user_claims(uid, {"role": role})


def _verify_role_from_id_token(id_token: str, expected_role: str) -> tuple[dict | None, str | None]:
    try:
        decoded = auth.verify_id_token(id_token, check_revoked=True)
    except auth.RevokedIdTokenError:
        return None, "token revoked"
    except auth.ExpiredIdTokenError:
        return None, "token expired"
    except auth.InvalidIdTokenError:
        return None, "invalid token"
    except auth.CertificateFetchError:
        return None, "auth verification unavailable"
    if decoded.get("role") != expected_role:
        return None, "forbidden"
    return decoded, None


def _map_identity_error(status: int, body: dict) -> tuple[dict, int]:
    err = body.get("error") if isinstance(body.get("error"), dict) else {}
    msg = (err.get("message") or body.get("message") or "auth error").strip()
    if status == 400:
        if "EMAIL_NOT_FOUND" in msg or "INVALID_PASSWORD" in msg or "INVALID_LOGIN_CREDENTIALS" in msg:
            return {"error": msg}, 401
        return {"error": msg}, 400
    if status == 403:
        return {"error": msg}, 403
    if status == 404:
        return {"error": msg}, 404
    return {"error": msg}, 502 if status >= 500 else status


def _parse_request_json(request) -> tuple[dict | None, tuple | None]:
    try:
        body = request.get_json(silent=True)
    except Exception:
        return None, _json_response({"error": "invalid JSON body"}, 400)
    if not isinstance(body, dict):
        return None, _json_response({"error": "JSON object body required"}, 400)
    return body, None


def _handle_signup(request, role: str):
    if request.method != "POST":
        return _json_response({"error": "method not allowed"}, 405)

    body, err = _parse_request_json(request)
    if err:
        return err

    _ensure_firebase()

    try:
        _require_api_key()
    except RuntimeError as e:
        return _json_response({"error": str(e)}, 500)

    email = body.get("email")
    password = body.get("password")
    google_id_token = body.get("googleIdToken") or body.get("id_token")

    try:
        if google_id_token:
            if not isinstance(google_id_token, str) or not google_id_token.strip():
                return _json_response({"error": "googleIdToken required"}, 400)
            raw, st = _sign_in_google_id_token(google_id_token.strip())
            if st != 200:
                return _map_identity_error(st, raw)
            if raw.get("isNewUser") is False:
                return _json_response({"error": "account already exists"}, 409)
            uid = raw.get("localId")
            if not uid:
                return _json_response({"error": "missing localId from IdP response"}, 502)
            _set_role_claim(uid, role)
            refresh = raw.get("refreshToken")
            if not refresh:
                return _json_response({"error": "missing refreshToken from IdP response"}, 502)
            ref_body, ref_st = _refresh_tokens(refresh)
            if ref_st != 200:
                return _map_identity_error(ref_st, ref_body)
            id_tok = ref_body.get("id_token")
            if not id_tok:
                return _json_response({"error": "missing id_token after refresh"}, 502)
            up_body, up_st = _sync_profile_signup(
                id_tok, uid, raw.get("email"), role
            )
            if up_st != 200:
                try:
                    auth.delete_user(uid)
                except fb_exc.FirebaseError:
                    pass
                return _json_response(
                    {
                        "error": "profile upsert failed",
                        "detail": up_body.get("error")
                        if isinstance(up_body, dict)
                        else up_body,
                    },
                    502,
                )
            return _json_response(_normalize_token_bundle(raw, ref_body), 200)

        if not email or not isinstance(email, str):
            return _json_response({"error": "email required"}, 400)
        if not password or not isinstance(password, str):
            return _json_response({"error": "password required"}, 400)

        try:
            user = auth.create_user(email=email.strip(), password=password)
        except auth.EmailAlreadyExistsError:
            return _json_response({"error": "email already in use"}, 409)
        except fb_exc.FirebaseError as e:
            return _json_response({"error": str(e)}, 400)

        _set_role_claim(user.uid, role)
        raw, st = _sign_in_password(email.strip(), password)
        if st != 200:
            try:
                auth.delete_user(user.uid)
            except fb_exc.FirebaseError:
                pass
            return _map_identity_error(st, raw)
        refresh = raw.get("refreshToken")
        if not refresh:
            return _json_response({"error": "missing refreshToken"}, 502)
        ref_body, ref_st = _refresh_tokens(refresh)
        if ref_st != 200:
            return _map_identity_error(ref_st, ref_body)
        id_tok = ref_body.get("id_token")
        if not id_tok:
            return _json_response({"error": "missing id_token after refresh"}, 502)
        up_body, up_st = _sync_profile_signup(
            id_tok, user.uid, email.strip(), role
        )
        if up_st != 200:
            try:
                auth.delete_user(user.uid)
            except fb_exc.FirebaseError:
                pass
            return _json_response(
                {
                    "error": "profile upsert failed",
                    "detail": up_body.get("error")
                    if isinstance(up_body, dict)
                    else up_body,
                },
                502,
            )
        return _json_response(_normalize_token_bundle(raw, ref_body), 200)

    except RuntimeError as e:
        return _json_response({"error": str(e)}, 500)
    except fb_exc.FirebaseError as e:
        return _json_response({"error": str(e)}, 500)


def _handle_login(request, role: str):
    if request.method != "POST":
        return _json_response({"error": "method not allowed"}, 405)

    body, err = _parse_request_json(request)
    if err:
        return err

    _ensure_firebase()

    try:
        _require_api_key()
    except RuntimeError as e:
        return _json_response({"error": str(e)}, 500)

    email = body.get("email")
    password = body.get("password")
    google_id_token = body.get("googleIdToken") or body.get("id_token")

    try:
        if google_id_token:
            if not isinstance(google_id_token, str) or not google_id_token.strip():
                return _json_response({"error": "googleIdToken required"}, 400)
            raw, st = _sign_in_google_id_token(google_id_token.strip())
            if st != 200:
                return _map_identity_error(st, raw)
            id_tok = raw.get("idToken")
            if not id_tok:
                return _json_response({"error": "missing idToken"}, 502)
            _, verr = _verify_role_from_id_token(id_tok, role)
            if verr == "forbidden":
                return _json_response({"error": "forbidden"}, 403)
            if verr:
                return _json_response({"error": verr}, 401)
            uid = raw.get("localId")
            if not uid:
                return _json_response({"error": "missing localId"}, 502)
            up_body, up_st = _sync_profile_login(
                id_tok, uid, raw.get("email"), role
            )
            if up_st != 200:
                return _json_response(
                    {
                        "error": "profile sync failed",
                        "detail": up_body.get("error")
                        if isinstance(up_body, dict)
                        else up_body,
                    },
                    503,
                )
            return _json_response(_normalize_token_bundle(raw), 200)

        if not email or not isinstance(email, str):
            return _json_response({"error": "email required"}, 400)
        if not password or not isinstance(password, str):
            return _json_response({"error": "password required"}, 400)

        raw, st = _sign_in_password(email.strip(), password)
        if st != 200:
            return _map_identity_error(st, raw)
        id_tok = raw.get("idToken")
        if not id_tok:
            return _json_response({"error": "missing idToken"}, 502)
        _, verr = _verify_role_from_id_token(id_tok, role)
        if verr == "forbidden":
            return _json_response({"error": "forbidden"}, 403)
        if verr:
            return _json_response({"error": verr}, 401)
        uid = raw.get("localId")
        if not uid:
            return _json_response({"error": "missing localId"}, 502)
        up_body, up_st = _sync_profile_login(
            id_tok, uid, raw.get("email"), role
        )
        if up_st != 200:
            return _json_response(
                {
                    "error": "profile sync failed",
                    "detail": up_body.get("error")
                    if isinstance(up_body, dict)
                    else up_body,
                },
                503,
            )
        return _json_response(_normalize_token_bundle(raw), 200)

    except RuntimeError as e:
        return _json_response({"error": str(e)}, 500)
    except fb_exc.FirebaseError as e:
        return _json_response({"error": str(e)}, 500)


@functions_framework.http
def realtor_signup(request):
    return _handle_signup(request, "realtor")


@functions_framework.http
def internal_signup(request):
    return _handle_signup(request, "internal")


@functions_framework.http
def realtor_login(request):
    return _handle_login(request, "realtor")


@functions_framework.http
def internal_login(request):
    return _handle_login(request, "internal")

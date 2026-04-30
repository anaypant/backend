"""Auth Cloud Functions: realtor/internal signup and login (password + Google via Identity Toolkit REST).

Profile writes go to the internal DB gateway: ``Authorization`` carries the Google OIDC token;
``X-ACS-Application-Authorization`` carries the Firebase ID token (see docs/acs-internal-request-contract.md).
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request

from google.auth.transport.requests import Request
from google.oauth2 import id_token as oauth_id_token

import acs_internal as acs
import email_profile_reconcile
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


def _db_read(id_token: str, doc_path: str) -> tuple[dict, int]:
    return _post_db(id_token, "/db/read/", {"path": doc_path})


def _post_db_platform(acting_uid: str, path_suffix: str, payload: dict) -> tuple[dict, int]:
    """Internal DB gateway with platform OIDC + X-ACS-Acting-Uid (same contract as integration callers)."""
    host = (os.environ.get("DB_INTERNAL_GATEWAY_HOSTNAME") or "").strip().rstrip("/")
    audience = f"https://{host}"
    infra = oauth_id_token.fetch_id_token(Request(), audience)
    url = _db_internal_origin() + path_suffix
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {infra}",
            "X-ACS-Acting-Uid": acting_uid,
            "X-ACS-Platform-Authorization": f"Bearer {infra}",
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


def _best_effort_reconcile_profile(
    id_token: str, uid: str, email: str | None, role: str
) -> None:
    try:
        email_profile_reconcile.reconcile_after_auth(
            uid,
            email,
            role,
            id_token,
            db_read=_db_read,
            db_upsert=_db_upsert,
            platform_post=_post_db_platform,
        )
    except Exception as e:
        logging.getLogger(__name__).warning("email profile reconcile failed: %s", e)


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
    if role == "internal":
        auth.set_custom_user_claims(uid, {"role": "internal", "admin": True})
    else:
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
    # Admins are a superset of all roles: they can log in via any role endpoint.
    # This mirrors the DB layer's _is_admin() which also grants full access when admin==True.
    if decoded.get("admin") is True:
        return decoded, None
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


def _normalize_email_addr(email: str | None) -> str:
    return (email or "").strip().lower()


def _sign_in_with_custom_token(custom_token: str) -> tuple[dict, int]:
    key = _require_api_key()
    url = (
        "https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken"
        f"?key={urllib.parse.quote(key)}"
    )
    return _post_json(
        url,
        {"token": custom_token, "returnSecureToken": True},
    )


def _google_login_resolve_canonical_uid(
    raw: dict, role: str
) -> tuple[dict, bool, str | None]:
    """
    When duplicate-email accounts exist, ``signInWithIdp`` may return a different ``localId``
    than ``get_user_by_email`` (the user record that still has the password hash). Exchange the
    Google IdP session for a Firebase session on the **canonical** UID so password sign-in and
    Google sign-in target the same Auth user.
    """
    idp_uid = raw.get("localId")
    email_raw = raw.get("email")
    if not idp_uid or not isinstance(email_raw, str) or not email_raw.strip():
        return raw, False, None
    norm = _normalize_email_addr(email_raw)
    try:
        canonical_uid = auth.get_user_by_email(norm).uid
    except Exception:
        return raw, False, None
    if canonical_uid == idp_uid:
        return raw, False, None
    try:
        canon_user = auth.get_user(canonical_uid)
        idp_user = auth.get_user(idp_uid)
    except fb_exc.FirebaseError:
        return raw, False, None
    if _normalize_email_addr(canon_user.email) != norm:
        return raw, False, None
    if _normalize_email_addr(idp_user.email) != norm:
        return raw, False, None
    _set_role_claim(canonical_uid, role)
    try:
        custom_tok = auth.create_custom_token(canonical_uid, {"role": role})
    except fb_exc.FirebaseError as e:
        logging.getLogger(__name__).warning(
            "canonical uid custom token failed (keeping IdP session): %s", e
        )
        return raw, False, None
    raw2, st2 = _sign_in_with_custom_token(custom_tok)
    if st2 != 200:
        logging.getLogger(__name__).warning(
            "signInWithCustomToken failed st=%s (keeping IdP session): %s", st2, raw2
        )
        return raw, False, None
    return raw2, True, custom_tok


def _send_password_reset_email(email: str) -> tuple[dict, int]:
    key = _require_api_key()
    url = (
        "https://identitytoolkit.googleapis.com/v1/accounts:sendOobCode"
        f"?key={urllib.parse.quote(key)}"
    )
    return _post_json(
        url,
        {"requestType": "PASSWORD_RESET", "email": email.strip()},
    )


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
            uid = raw.get("localId")
            if not uid:
                return _json_response({"error": "missing localId from IdP response"}, 502)
            # True when Firebase just created the account via signInWithIdp; False when the
            # Firebase Auth account already existed (created by a prior Google sign-in, SDK test,
            # Firebase console, etc.).  In the "False" case we still allow first-time ACS
            # provisioning — but only if the account has no ACS role claim yet.
            is_new_firebase_account = raw.get("isNewUser") is not False
            if not is_new_firebase_account:
                try:
                    fb_user = auth.get_user(uid)
                    existing_role = (fb_user.custom_claims or {}).get("role")
                    if existing_role:
                        # Account is already provisioned in ACS — this is a true duplicate.
                        return _json_response({"error": "account already exists"}, 409)
                    # No ACS role claim: Firebase account exists but was never onboarded through
                    # ACS signup.  Provision it now so the user is not caught in a dead-end where
                    # signup returns 409 and login returns 403.
                    logging.getLogger(__name__).info(
                        "Provisioning existing Firebase account %s as first-time ACS %s", uid, role
                    )
                except fb_exc.FirebaseError as e:
                    logging.getLogger(__name__).warning(
                        "Could not check custom claims for uid %s: %s — treating as duplicate", uid, e
                    )
                    return _json_response({"error": "account already exists"}, 409)
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
                if is_new_firebase_account:
                    # Only delete if WE just created this Firebase account; don't wipe an
                    # existing account that was merely being provisioned into ACS.
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
            _best_effort_reconcile_profile(id_tok, uid, raw.get("email"), role)
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
        _best_effort_reconcile_profile(id_tok, user.uid, email.strip(), role)
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
            raw, merged_dup, custom_for_client = _google_login_resolve_canonical_uid(raw, role)
            id_tok = raw.get("idToken")
            if not id_tok:
                return _json_response({"error": "missing idToken"}, 502)
            _, verr = _verify_role_from_id_token(id_tok, role)
            if verr == "forbidden":
                return _json_response(
                    {
                        "error": "account_not_registered",
                        "detail": (
                            f"This Google account exists in Firebase but has no ACS '{role}' role. "
                            "Use the sign-up path to provision it, or contact an administrator."
                        ),
                    },
                    403,
                )
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
            _best_effort_reconcile_profile(id_tok, uid, raw.get("email"), role)
            out = _normalize_token_bundle(raw)
            if merged_dup and custom_for_client:
                out["mergedDuplicateGoogleAccount"] = True
                out["customToken"] = custom_for_client
            return _json_response(out, 200)

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
            return _json_response(
                {
                    "error": "account_not_registered",
                    "detail": (
                        f"This account exists in Firebase but has no ACS '{role}' role. "
                        "Use the sign-up path to provision it, or contact an administrator."
                    ),
                },
                403,
            )
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
        _best_effort_reconcile_profile(id_tok, uid, raw.get("email"), role)
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


@functions_framework.http
def promote_admin(request):
    """POST JSON { "uid": str } — elevate an existing user to internal+admin.

    Caller must supply one of:
      - Platform OIDC: Authorization: Bearer <SA OIDC> where SA email == BACKEND_SERVICE_ACCOUNT_EMAIL
      - Existing admin Firebase JWT: X-ACS-Application-Authorization: Bearer <id_token> with admin==true

    This endpoint exists so ACS developers can promote existing accounts without re-signup.
    The uid must already exist in Firebase Auth; their role claim is set to {"role":"internal","admin":true}.
    """
    if request.method != "POST":
        return _json_response({"error": "method not allowed"}, 405)

    _ensure_firebase()

    body, err = _parse_request_json(request)
    if err:
        return err

    uid_to_promote = (body.get("uid") or "").strip()
    if not uid_to_promote:
        return _json_response({"error": "uid is required"}, 400)

    caller_authorized = False

    # Path 1: platform OIDC SA token.
    platform_email = (os.environ.get("BACKEND_SERVICE_ACCOUNT_EMAIL") or "").strip()
    authz_header = request.headers.get("Authorization") or ""
    if authz_header.startswith("Bearer ") and platform_email:
        token = authz_header[7:].strip()
        try:
            claims = oauth_id_token.verify_oauth2_token(token, Request(), audience=None)
            if (claims.get("email") or "").strip() == platform_email:
                caller_authorized = True
        except Exception:
            pass

    # Path 2: existing admin's Firebase JWT.
    if not caller_authorized:
        app_jwt_header = request.headers.get(acs.APPLICATION_AUTHORIZATION_HEADER) or ""
        if app_jwt_header.startswith("Bearer "):
            app_token = app_jwt_header[7:].strip()
            try:
                decoded = auth.verify_id_token(app_token, check_revoked=True)
                if decoded.get("admin") is True or decoded.get("role") == "admin":
                    caller_authorized = True
            except Exception:
                pass

    if not caller_authorized:
        return _json_response({"error": "forbidden: platform SA or existing admin token required"}, 403)

    try:
        auth.get_user(uid_to_promote)
    except auth.UserNotFoundError:
        return _json_response({"error": "user not found"}, 404)
    except fb_exc.FirebaseError as e:
        return _json_response({"error": str(e)}, 500)

    try:
        auth.set_custom_user_claims(uid_to_promote, {"role": "internal", "admin": True})
    except fb_exc.FirebaseError as e:
        return _json_response({"error": str(e)}, 500)

    return _json_response({"ok": True, "uid": uid_to_promote, "claims": {"role": "internal", "admin": True}}, 200)


@functions_framework.http
def password_reset(request):
    """POST JSON { email } — Identity Toolkit PASSWORD_RESET (same as Firebase client sendPasswordResetEmail)."""
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
    if not email or not isinstance(email, str) or not email.strip():
        return _json_response({"error": "email required"}, 400)

    raw, st = _send_password_reset_email(email.strip())
    if st != 200:
        if not isinstance(raw, dict):
            raw = {"error": str(raw)}
        return _map_identity_error(st, raw)

    return _json_response({"ok": True}, 200)

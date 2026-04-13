import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

import acs_internal as acs

from store import gcp_identity

HEADER_ACTING = "X-ACS-Acting-Uid"
HEADER_PLATFORM_AUTH = "X-ACS-Platform-Authorization"


def json_response(payload: dict, status: int):
    return (json.dumps(payload), status, {"Content-Type": "application/json"})


def integration_auth_error_response(err: str):
    """Standard JSON for Firebase / gateway identity failures on realtor-only routes (trace 401/403)."""
    hints = {
        "missing bearer token": (
            "Send Authorization: Bearer <Firebase ID token> on the public API. "
            "Internal hops use Authorization for Firebase and X-GCP-Identity for Google OIDC (invoker)."
        ),
        "invalid token": "ID token failed verification (wrong project, malformed, or not a Firebase auth token).",
        "token expired": "Refresh the Firebase session and retry with a new ID token.",
        "token revoked": "User signed out or token was revoked; sign in again.",
        "forbidden": "Authenticated user is not a realtor for this route.",
        "invalid gateway identity": "X-Endpoint-API-UserInfo was present but missing user_id/sub or realtor role.",
    }
    payload: dict = {"error": err, "phase": "integration_auth"}
    h = hints.get(err)
    if h:
        payload["hint"] = h
    return json_response(payload, 401 if err != "forbidden" else 403)


def now_epoch() -> int:
    return int(time.time())


def db_origin() -> str:
    host = gcp_identity.normalize_internal_gateway_hostname(os.environ.get("DB_INTERNAL_GATEWAY_HOSTNAME") or "")
    if not host:
        raise RuntimeError("DB_INTERNAL_GATEWAY_HOSTNAME is not set")
    return f"https://{host}"


def core_origin() -> str:
    host = gcp_identity.normalize_internal_gateway_hostname(os.environ.get("CORE_INTERNAL_GATEWAY_HOSTNAME") or "")
    if not host:
        raise RuntimeError("CORE_INTERNAL_GATEWAY_HOSTNAME is not set")
    return f"https://{host}"


def public_integration_base_url(request) -> str:
    configured = (os.environ.get("ACS_PUBLIC_INTEGRATION_BASE_URL") or "").strip().rstrip("/")
    if configured:
        return configured
    host = request.headers.get("X-Forwarded-Host") or request.host
    proto = request.headers.get("X-Forwarded-Proto") or "https"
    return f"{proto}://{host}".rstrip("/")


def post_json(url: str, payload: dict, *, user_jwt: str | None = None, headers: dict | None = None, timeout: int = 60) -> tuple[dict, int]:
    body = json.dumps(payload).encode("utf-8")
    req_headers = {"Content-Type": "application/json"}
    if user_jwt:
        req_headers["Authorization"] = f"Bearer {user_jwt}"
        req_headers[acs.GCP_INFRA_IDENTITY_HEADER] = (
            f"Bearer {gcp_identity.id_token_for_db_gateway()}"
        )
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, data=body, method="POST", headers=req_headers)
    return _exec(req, timeout=timeout)


def post_json_platform(url: str, payload: dict, *, acting_uid: str, timeout: int = 60) -> tuple[dict, int]:
    """DB internal gateway as platform SA; acting_uid is the realtor Firebase uid for authz."""
    token = gcp_identity.id_token_for_db_gateway()
    body = json.dumps(payload).encode("utf-8")
    req_headers = {
        "Content-Type": "application/json",
        HEADER_ACTING: acting_uid,
        f"{HEADER_PLATFORM_AUTH}": f"Bearer {token}",
    }
    req = urllib.request.Request(url, data=body, method="POST", headers=req_headers)
    return _exec(req, timeout=timeout)


def post_json_secrets_platform(url: str, payload: dict, *, acting_uid: str, timeout: int = 60) -> tuple[dict, int]:
    """Secrets internal gateway as platform SA; acting_uid must match the secret's realtor scope."""
    token = gcp_identity.id_token_for_secrets_gateway()
    body = json.dumps(payload).encode("utf-8")
    req_headers = {
        "Content-Type": "application/json",
        HEADER_ACTING: acting_uid,
        HEADER_PLATFORM_AUTH: f"Bearer {token}",
    }
    req = urllib.request.Request(url, data=body, method="POST", headers=req_headers)
    return _exec(req, timeout=timeout)


def get_json(url: str, *, headers: dict | None = None, timeout: int = 60) -> tuple[dict, int]:
    req_headers = headers or {}
    req = urllib.request.Request(url, method="GET", headers=req_headers)
    return _exec(req, timeout=timeout)


def delete_json(url: str, *, headers: dict | None = None, timeout: int = 60) -> tuple[dict, int]:
    req_headers = headers or {}
    req = urllib.request.Request(url, method="DELETE", headers=req_headers)
    return _exec(req, timeout=timeout)


def post_form(url: str, form: dict[str, str], *, headers: dict | None = None, timeout: int = 60) -> tuple[dict, int]:
    body = urllib.parse.urlencode(form).encode("utf-8")
    req_headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, method="POST", data=body, headers=req_headers)
    return _exec(req, timeout=timeout)


def _exec(req: urllib.request.Request, *, timeout: int) -> tuple[dict, int]:
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            if not raw:
                return {}, resp.status
            try:
                return json.loads(raw), resp.status
            except json.JSONDecodeError:
                return {"raw": raw}, resp.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            return json.loads(raw), e.code
        except json.JSONDecodeError:
            return {"error": raw or "upstream error"}, e.code

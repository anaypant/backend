import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

import acs_internal as acs


def json_response(payload: dict, status: int):
    return (json.dumps(payload), status, {"Content-Type": "application/json"})


def now_epoch() -> int:
    return int(time.time())


def db_origin() -> str:
    host = (os.environ.get("DB_INTERNAL_GATEWAY_HOSTNAME") or "").strip()
    if not host:
        raise RuntimeError("DB_INTERNAL_GATEWAY_HOSTNAME is not set")
    return f"https://{host.rstrip('/')}"


def core_origin() -> str:
    host = (os.environ.get("CORE_INTERNAL_GATEWAY_HOSTNAME") or "").strip()
    if not host:
        raise RuntimeError("CORE_INTERNAL_GATEWAY_HOSTNAME is not set")
    return f"https://{host.rstrip('/')}"


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
        req_headers[acs.USER_JWT_HEADER] = f"Bearer {user_jwt}"
    if headers:
        req_headers.update(headers)
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

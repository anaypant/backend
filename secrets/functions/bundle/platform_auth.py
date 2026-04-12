"""Verify Google OIDC from API Gateway (platform SA) + optional acting uid header."""

from __future__ import annotations

import os
import re

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

HEADER_ACTING = "X-ACS-Acting-Uid"
HEADER_PLATFORM_AUTH = "X-ACS-Platform-Authorization"

_ACTING_UID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")


def _bearer_from_header(request, header_name: str) -> str | None:
    raw = request.headers.get(header_name) or ""
    parts = raw.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        t = parts[1].strip()
        return t or None
    return None


def _candidate_audiences(request) -> list[str]:
    out: list[str] = []
    env_host = (os.environ.get("ACS_SECRETS_GATEWAY_HOSTNAME") or "").strip().rstrip("/")
    if env_host:
        out.append(f"https://{env_host}")
    xfh = (request.headers.get("X-Forwarded-Host") or "").split(",")[0].strip().rstrip("/")
    if xfh and f"https://{xfh}" not in out:
        out.append(f"https://{xfh}")
    host = (request.headers.get("Host") or "").split(",")[0].strip().rstrip("/")
    if host and not host.endswith(".run.app") and f"https://{host}" not in out:
        out.append(f"https://{host}")
    return out


def acting_uid_valid(uid: str) -> bool:
    return bool(uid and _ACTING_UID_RE.match(uid))


def verify_platform_request(request) -> tuple[dict | None, tuple[dict, int] | None]:
    """
    Returns (claims_dict, None) on success, or (None, (error_body, status)) on failure.
    """
    expected_email = (os.environ.get("ACS_PLATFORM_SERVICE_ACCOUNT_EMAIL") or "").strip()
    if not expected_email:
        return None, ({"error": "ACS_PLATFORM_SERVICE_ACCOUNT_EMAIL not configured"}, 503)

    audiences = _candidate_audiences(request)
    if not audiences:
        return None, ({"error": "secrets gateway audience not configured"}, 503)

    token = _bearer_from_header(request, HEADER_PLATFORM_AUTH) or _bearer_from_header(request, "Authorization")
    if not token:
        return None, ({"error": "missing platform bearer token"}, 401)

    req = google_requests.Request()
    claims = None
    last_err: str | None = None
    for aud in audiences:
        try:
            claims = id_token.verify_oauth2_token(token, req, audience=aud)
            break
        except ValueError as e:
            last_err = str(e)
            continue
    if claims is None:
        return None, ({"error": "invalid platform identity token", "detail": last_err or "audience mismatch"}, 401)

    email = (claims.get("email") or "").strip()
    if email != expected_email:
        return None, ({"error": "forbidden: platform caller not allowed"}, 403)

    return claims, None


def require_acting_uid(request, scope_id: str) -> tuple[str | None, tuple[dict, int] | None]:
    acting = (request.headers.get(HEADER_ACTING) or "").strip()
    if not acting:
        return None, ({"error": "missing X-ACS-Acting-Uid"}, 401)
    if not acting_uid_valid(acting):
        return None, ({"error": "invalid X-ACS-Acting-Uid"}, 400)
    if acting != scope_id:
        return None, ({"error": "acting uid does not match scopeId"}, 403)
    return acting, None

import os
import re

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

_ACTING_UID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")

HEADER_ACTING = "X-ACS-Acting-Uid"
HEADER_PLATFORM_AUTH = "X-ACS-Platform-Authorization"
HEADER_GCP_INFRA_IDENTITY = "X-GCP-Identity"


def _expected_audience() -> str | None:
    host = (os.environ.get("ACS_DB_GATEWAY_HOSTNAME") or "").strip().rstrip("/")
    if not host:
        return None
    return f"https://{host}"


def _expected_platform_email() -> str | None:
    e = (os.environ.get("ACS_PLATFORM_SERVICE_ACCOUNT_EMAIL") or "").strip()
    return e or None


def acting_uid_valid(uid: str) -> bool:
    return bool(uid and _ACTING_UID_RE.match(uid))


def _bearer_from_header(request, header_name: str) -> str | None:
    raw = request.headers.get(header_name) or ""
    parts = raw.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        t = parts[1].strip()
        return t or None
    return None


def try_platform_actor(request):
    """
    If X-ACS-Acting-Uid is set, require Google OIDC (platform SA) on X-ACS-Platform-Authorization,
    Authorization, or X-GCP-Identity (legacy).
    Returns (decoded_dict, None) on success, or (None, (error_body, status)) on failure.
    If acting header absent, returns (None, None) to continue Firebase path.
    """
    acting = (request.headers.get(HEADER_ACTING) or "").strip()
    if not acting:
        return None, None

    if not acting_uid_valid(acting):
        return None, ({"error": "invalid X-ACS-Acting-Uid"}, 400)

    aud = _expected_audience()
    expected_email = _expected_platform_email()
    if not aud or not expected_email:
        return None, ({"error": "platform db auth not configured"}, 503)

    token = (
        _bearer_from_header(request, HEADER_PLATFORM_AUTH)
        or _bearer_from_header(request, "Authorization")
        or _bearer_from_header(request, HEADER_GCP_INFRA_IDENTITY)
    )
    if not token:
        return None, ({"error": "missing platform bearer token"}, 401)

    try:
        req = google_requests.Request()
        claims = id_token.verify_oauth2_token(token, req, audience=aud)
    except ValueError:
        return None, ({"error": "invalid platform identity token"}, 401)

    email = (claims.get("email") or "").strip()
    if email != expected_email:
        return None, ({"error": "forbidden: platform caller not allowed"}, 403)

    return {"uid": acting}, None

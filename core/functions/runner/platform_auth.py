"""Defense-in-depth OIDC verification for the core runner.

The core runner is protected at the infrastructure level (Cloud Run IAM + API Gateway). This
module adds in-handler verification as a secondary layer: callers must present a Google OIDC
token issued for the platform service account.

Audience: ``https://{CORE_INTERNAL_GATEWAY_HOSTNAME}`` (the acs-core-internal API gateway).
If ``CORE_INTERNAL_GATEWAY_HOSTNAME`` is unset (first-deploy bootstrap), verification is skipped
with a warning logged — do not leave unset in production.

Caller contract: ``Authorization: Bearer <OIDC token>`` where the OIDC token has
``aud = https://{CORE_INTERNAL_GATEWAY_HOSTNAME}`` and ``email = BACKEND_SERVICE_ACCOUNT_EMAIL``.
"""

from __future__ import annotations

import logging
import os

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

_logger = logging.getLogger(__name__)

HEADER_PLATFORM_AUTH = "X-ACS-Platform-Authorization"
HEADER_GCP_INFRA_IDENTITY = "X-GCP-Identity"


def _expected_audience() -> str | None:
    host = (os.environ.get("CORE_INTERNAL_GATEWAY_HOSTNAME") or "").strip().rstrip("/")
    if not host:
        return None
    return f"https://{host}"


def _expected_platform_email() -> str | None:
    e = (os.environ.get("BACKEND_SERVICE_ACCOUNT_EMAIL") or "").strip()
    return e or None


def _bearer_from_header(request, header_name: str) -> str | None:
    raw = request.headers.get(header_name) or ""
    parts = raw.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        t = parts[1].strip()
        return t or None
    return None


def verify_platform_caller(request) -> tuple[bool, str | None]:
    """
    Verify that the caller is the platform SA via OIDC.

    Returns (ok, error_message).
    - (True, None): verified.
    - (True, None): CORE_INTERNAL_GATEWAY_HOSTNAME not set — verification skipped (bootstrap mode).
    - (False, message): verification failed; caller should return 401/403.
    """
    aud = _expected_audience()
    if not aud:
        _logger.warning(
            "core platform_auth: CORE_INTERNAL_GATEWAY_HOSTNAME not set — "
            "in-handler OIDC verification skipped. Set this env var in production."
        )
        return True, None

    expected_email = _expected_platform_email()
    if not expected_email:
        _logger.warning(
            "core platform_auth: BACKEND_SERVICE_ACCOUNT_EMAIL not set — "
            "in-handler OIDC verification skipped."
        )
        return True, None

    token = (
        _bearer_from_header(request, "Authorization")
        or _bearer_from_header(request, HEADER_PLATFORM_AUTH)
        or _bearer_from_header(request, HEADER_GCP_INFRA_IDENTITY)
    )
    if not token:
        return False, "missing platform bearer token"

    try:
        req = google_requests.Request()
        claims = id_token.verify_oauth2_token(token, req, audience=aud)
    except ValueError as e:
        return False, f"invalid platform identity token: {e}"

    email = (claims.get("email") or "").strip()
    if email != expected_email:
        return False, f"forbidden: unexpected caller {email!r}"

    return True, None

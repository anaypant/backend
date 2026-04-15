"""Verify Google OIDC from Cloud Tasks (service account) for internal workers."""

import os

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token


def verify_cloud_tasks_caller(request) -> tuple[dict | None, str | None]:
    """
    Cloud Tasks HTTP targets send Authorization: Bearer <OIDC> for the configured service account.
    Audience must match FUB_WEBHOOK_SYNC_OIDC_AUDIENCE (same as task oidc_token.audience).
    """
    authz = request.headers.get("Authorization") or ""
    if not authz.startswith("Bearer "):
        return None, "missing bearer"
    token = authz[7:].strip()
    audience = (os.environ.get("FUB_WEBHOOK_SYNC_OIDC_AUDIENCE") or os.environ.get("FUB_WEBHOOK_SYNC_WORKER_URL") or "").strip().rstrip("/")
    if not audience:
        return None, "FUB_WEBHOOK_SYNC_OIDC_AUDIENCE not configured"
    expected_email = (os.environ.get("BACKEND_SERVICE_ACCOUNT_EMAIL") or "").strip()
    if not expected_email:
        return None, "BACKEND_SERVICE_ACCOUNT_EMAIL not configured"
    try:
        info = id_token.verify_oauth2_token(token, google_requests.Request(), audience=audience)
    except Exception as e:
        return None, f"invalid token: {e}"
    email = info.get("email") or info.get("email_address")
    if email != expected_email:
        return None, "caller is not the platform service account"
    return info, None

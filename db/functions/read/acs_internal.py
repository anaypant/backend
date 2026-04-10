"""ACS contract: ESP may set Authorization to SA OIDC; end-user identity from gateway or X-Firebase-Authorization."""

import base64
import binascii
import json

USER_JWT_HEADER = "X-Firebase-Authorization"
ENDPOINT_USER_INFO_HEADER = "X-Endpoint-API-UserInfo"


def decode_endpoint_user_info_claims(request) -> dict | None:
    raw = (request.headers.get(ENDPOINT_USER_INFO_HEADER) or "").strip()
    if not raw:
        return None
    try:
        pad = "=" * ((4 - len(raw) % 4) % 4)
        b = base64.urlsafe_b64decode(raw + pad)
        out = json.loads(b.decode("utf-8"))
        return out if isinstance(out, dict) else None
    except (ValueError, json.JSONDecodeError, binascii.Error):
        return None

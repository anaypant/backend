"""ACS end-user identity for HTTP handlers.

**Public API:** clients send ``Authorization: Bearer <Firebase ID token>``. ESP validates at the
gateway and forwards claims as ``X-Endpoint-API-UserInfo``.

**Internal service calls:** send Firebase in ``Authorization`` and Google ID token (invoker) in
``X-GCP-Identity``. Legacy: ``X-ACS-User-Authorization`` may carry the Firebase token if
``Authorization`` is reserved for OIDC.
"""

import base64
import binascii
import json

USER_AUTHORIZATION_HEADER = "X-ACS-User-Authorization"
USER_JWT_HEADER = USER_AUTHORIZATION_HEADER

GCP_INFRA_IDENTITY_HEADER = "X-GCP-Identity"

ENDPOINT_USER_INFO_HEADER = "X-Endpoint-API-UserInfo"

END_USER_BEARER_HEADER_ORDER = (
    "Authorization",
    USER_AUTHORIZATION_HEADER,
)


def decode_endpoint_user_info_claims(request) -> dict | None:
    """Base64url JSON claims from ESP after Firebase JWT validation at the public gateway."""
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


def parse_bearer_header(request, header_name: str) -> str | None:
    raw = request.headers.get(header_name) or ""
    parts = raw.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        t = parts[1].strip()
        return t or None
    return None

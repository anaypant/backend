"""ACS end-user identity for HTTP handlers.

**Internal contract:** ``Authorization`` = Google OIDC (transport). ``X-ACS-Application-Authorization``
= Firebase (or future ACS) JWT for application identity.

**Legacy:** ``X-ACS-User-Authorization`` (same as application JWT). ``X-GCP-Identity`` for OIDC
invoker (deprecated; prefer ``Authorization`` for OIDC on new callers).

**Public API:** clients may send Firebase in ``Authorization`` at the public gateway; ESP validates
and may set ``X-Endpoint-API-UserInfo``.
"""

import base64
import binascii
import json

APPLICATION_AUTHORIZATION_HEADER = "X-ACS-Application-Authorization"
USER_AUTHORIZATION_HEADER = "X-ACS-User-Authorization"
USER_JWT_HEADER = APPLICATION_AUTHORIZATION_HEADER

GCP_INFRA_IDENTITY_HEADER = "X-GCP-Identity"

ENDPOINT_USER_INFO_HEADER = "X-Endpoint-API-UserInfo"

END_USER_BEARER_HEADER_ORDER = (
    APPLICATION_AUTHORIZATION_HEADER,
    USER_AUTHORIZATION_HEADER,
    "Authorization",
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

import os
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2 import id_token as oauth_id_token


class SecretsOidcConfigError(Exception):
    """Raised when SECRETS_INTERNAL_JWT_AUDIENCE is missing; carries HTTP JSON for handle_request."""

    def __init__(self, payload: dict[str, Any], *, http_status: int = 503):
        super().__init__(str(payload.get("error", "secrets_oidc")))
        self.payload = payload
        self.http_status = http_status


def normalize_internal_gateway_hostname(raw: str) -> str:
    """
    Hostname only for https://HOST (no scheme, path, or trailing slash).
    Strips accidental https:// from Terraform/HCP copy-paste; otherwise urllib may
    resolve the wrong host and raise socket.gaierror (-3).
    """
    h = (raw or "").strip()
    while h:
        low = h.lower()
        if low.startswith("https://"):
            h = h[8:].strip()
        elif low.startswith("http://"):
            h = h[7:].strip()
        else:
            break
    if "/" in h:
        h = h.split("/", 1)[0].strip()
    if h.endswith(":443"):
        h = h[:-4].strip()
    return h.rstrip("/").strip()


def id_token_for_db_gateway() -> str:
    """Google ID token for calling acs-db-internal; audience must match DB platform_auth verification."""
    host = normalize_internal_gateway_hostname(os.environ.get("DB_INTERNAL_GATEWAY_HOSTNAME") or "")
    if not host:
        raise RuntimeError("DB_INTERNAL_GATEWAY_HOSTNAME is not set")
    audience = f"https://{host}"
    return oauth_id_token.fetch_id_token(Request(), audience)


def id_token_for_core_gateway() -> str:
    """Google ID token for calling acs-core-internal; audience must match core platform_auth verification."""
    host = normalize_internal_gateway_hostname(os.environ.get("CORE_INTERNAL_GATEWAY_HOSTNAME") or "")
    if not host:
        raise RuntimeError("CORE_INTERNAL_GATEWAY_HOSTNAME is not set")
    audience = f"https://{host}"
    return oauth_id_token.fetch_id_token(Request(), audience)


def id_token_for_secrets_gateway() -> str:
    """
    Google ID token for calling the internal secrets API Gateway.

    Audience **must** be ``SECRETS_INTERNAL_JWT_AUDIENCE`` (secrets-bridge Cloud Function URL, matching API Gateway
    ``jwt_audience``). There is **no** fallback to ``SECRETS_INTERNAL_GATEWAY_HOSTNAME`` — minting for ``*.gateway.dev``
    is rejected by secrets-bridge.
    """
    aud = (os.environ.get("SECRETS_INTERNAL_JWT_AUDIENCE") or "").strip().rstrip("/")
    if aud:
        return oauth_id_token.fetch_id_token(Request(), aud)

    gw_host = (os.environ.get("SECRETS_INTERNAL_GATEWAY_HOSTNAME") or "").strip() or None
    raise SecretsOidcConfigError(
        {
            "error": "secrets_oidc_audience_not_configured",
            "phase": "secrets_platform_oidc",
            "detail": (
                "SECRETS_INTERNAL_JWT_AUDIENCE is unset or empty; OIDC for acs-sec:// cannot be minted. "
                "Hostname-based minting is not supported (wrong aud for secrets-bridge)."
            ),
            "secretsInternalGatewayHostname": gw_host,
            "todo": (
                "Set SECRETS_INTERNAL_JWT_AUDIENCE on integration-bridge to the secrets-bridge Cloud Function URL "
                "(no trailing slash), e.g. terraform output -raw secrets_bridge_invoker_audience, then redeploy."
            ),
        },
        http_status=503,
    )

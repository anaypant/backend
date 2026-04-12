import os

from google.auth.transport.requests import Request
from google.oauth2 import id_token as oauth_id_token


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


def id_token_for_secrets_gateway() -> str:
    """Google ID token for calling acs-secrets-internal; audience must match secrets platform_auth."""
    host = normalize_internal_gateway_hostname(os.environ.get("SECRETS_INTERNAL_GATEWAY_HOSTNAME") or "")
    if not host:
        raise RuntimeError("SECRETS_INTERNAL_GATEWAY_HOSTNAME is not set")
    audience = f"https://{host}"
    return oauth_id_token.fetch_id_token(Request(), audience)

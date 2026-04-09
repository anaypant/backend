import os

from google.auth.transport.requests import Request
from google.oauth2 import id_token as oauth_id_token


def id_token_for_db_gateway() -> str:
    """Google ID token for calling acs-db-internal; audience must match DB platform_auth verification."""
    host = (os.environ.get("DB_INTERNAL_GATEWAY_HOSTNAME") or "").strip().rstrip("/")
    if not host:
        raise RuntimeError("DB_INTERNAL_GATEWAY_HOSTNAME is not set")
    audience = f"https://{host}"
    return oauth_id_token.fetch_id_token(Request(), audience)

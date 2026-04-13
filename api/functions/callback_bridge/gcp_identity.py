import os

from google.auth.transport.requests import Request
from google.oauth2 import id_token as oauth_id_token


def normalize_internal_gateway_hostname(raw: str) -> str:
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


def id_token_for_integration_gateway() -> str:
    host = normalize_internal_gateway_hostname(os.environ.get("INTEGRATION_INTERNAL_GATEWAY_HOSTNAME") or "")
    if not host:
        raise RuntimeError("INTEGRATION_INTERNAL_GATEWAY_HOSTNAME is not set")
    return oauth_id_token.fetch_id_token(Request(), f"https://{host}")

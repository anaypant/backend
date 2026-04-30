"""
Authenticated HTTP helper for the ACS CLI.

All commands call `request()` which:
  1. Resolves the base URL from config/override
  2. Injects the Authorization: Bearer header (with silent token refresh)
  3. Returns (http_status: int, body: dict | str)
  4. Raises CliError on network failure
"""
from __future__ import annotations

from typing import Any, Optional

import requests

from . import config


class CliError(RuntimeError):
    """Raised on network-level failures (not HTTP errors — those are returned to the caller)."""


def request(
    method: str,
    path: str,
    *,
    json: Optional[dict] = None,
    headers: Optional[dict] = None,
    auth: bool = True,
    base_url_override: Optional[str] = None,
    timeout: int = 30,
) -> tuple[int, Any]:
    """
    Send a request to the ACS public gateway.

    Returns (status_code, parsed_body).
    body is a dict if the response is JSON, otherwise a raw string.
    Raises CliError on connection failure.
    """
    base = config.get_base_url(base_url_override)
    url = f"{base}/{path.lstrip('/')}"

    req_headers: dict[str, str] = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)
    if auth:
        token = config.get_token()
        req_headers["Authorization"] = f"Bearer {token}"
        # Mirror the token as the app-authorization header so internal functions
        # behind the gateway can verify it (acs-internal-request-contract.md path 1).
        req_headers["X-ACS-Application-Authorization"] = f"Bearer {token}"

    try:
        resp = requests.request(
            method.upper(),
            url,
            json=json,
            headers=req_headers,
            timeout=timeout,
        )
    except requests.ConnectionError as e:
        raise CliError(f"Connection failed: {e}") from e
    except requests.Timeout:
        raise CliError(f"Request timed out after {timeout}s")

    # Parse body
    body: Any
    ct = resp.headers.get("content-type", "")
    if "application/json" in ct:
        try:
            body = resp.json()
        except ValueError:
            body = resp.text
    else:
        body = resp.text

    return resp.status_code, body

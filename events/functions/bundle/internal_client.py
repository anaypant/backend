"""
Agnostic client for POST /events/v1/publish from other ACS Cloud Functions.

Set env:
  EVENTS_INTERNAL_GATEWAY_HOSTNAME — hostname only (same as terraform output events_gateway_hostname)

Uses platform service account OIDC (runs as that SA on Cloud Functions Gen2).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from google.auth.transport.requests import Request
from google.oauth2 import id_token as oauth_id_token


def publish_domain_event(
    *,
    event_type: str,
    data: dict,
    source: str = "/acs/unknown",
    subject: str = "",
    acting_uid: str | None = None,
    correlation_id: str | None = None,
    events_gateway_hostname: str | None = None,
) -> tuple[dict, int]:
    """
    Publish a CloudEvents-shaped message to acs-domain-events via the internal API Gateway.

    Returns (response_json, http_status).
    """
    host = (events_gateway_hostname or os.environ.get("EVENTS_INTERNAL_GATEWAY_HOSTNAME") or "").strip()
    if not host:
        return {"error": "EVENTS_INTERNAL_GATEWAY_HOSTNAME not set"}, 503

    host = host.rstrip("/")
    if "://" in host:
        host = host.split("://", 1)[1].split("/")[0]

    audience = f"https://{host}"
    url = f"{audience}/events/v1/publish"

    token = oauth_id_token.fetch_id_token(Request(), audience)
    body_obj: dict = {"type": event_type, "source": source, "data": data}
    if subject:
        body_obj["subject"] = subject
    body = json.dumps(body_obj).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    if acting_uid:
        headers["X-ACS-Acting-Uid"] = acting_uid
    if correlation_id:
        headers["X-ACS-Correlation-Id"] = correlation_id

    req = urllib.request.Request(url, data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return (json.loads(raw) if raw else {}, resp.status)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            return (json.loads(raw), e.code)
        except json.JSONDecodeError:
            return ({"error": raw or "upstream error"}, e.code)

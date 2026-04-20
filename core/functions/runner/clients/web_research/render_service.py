"""Optional remote HTML snapshot (headless browser) service."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


def render_service_configured() -> bool:
    return bool((os.environ.get("ACS_RENDER_SERVICE_URL") or "").strip())


def fetch_rendered_html(target_url: str) -> tuple[str | None, int, str | None]:
    """
    POST ``{"url": "<target>"}`` to ``ACS_RENDER_SERVICE_URL``; expect JSON ``{"html": "..."}``
    or raw ``text/html`` body.

    Optional headers:
    - ``ACS_RENDER_SERVICE_TOKEN`` as ``Authorization: Bearer ...``
    """
    base = (os.environ.get("ACS_RENDER_SERVICE_URL") or "").strip().rstrip("/")
    if not base:
        return None, 0, "render_service_not_configured"

    token = (os.environ.get("ACS_RENDER_SERVICE_TOKEN") or "").strip()
    timeout = max(10, min(180, int((os.environ.get("ACS_RENDER_SERVICE_TIMEOUT_S") or "60").strip() or 60)))

    payload = {"url": target_url.strip()}
    body_bytes = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/html;q=0.9,*/*;q=0.8",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(base, data=body_bytes, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(6_000_000)
            st = int(resp.status)
            ctype = (resp.headers.get("Content-Type") or "").lower()
    except urllib.error.HTTPError as e:
        try:
            raw = e.read(500_000)
        except Exception:
            raw = b""
        return None, int(e.code), raw.decode("utf-8", errors="replace")[:2000]
    except Exception as e:
        return None, 599, str(e)

    text = raw.decode("utf-8", errors="replace")
    if "application/json" in ctype or text.lstrip().startswith("{"):
        try:
            obj: dict[str, Any] = json.loads(text)
        except json.JSONDecodeError:
            return None, st, "invalid_json_from_render_service"
        html = obj.get("html")
        if isinstance(html, str) and html.strip():
            return html, st, None
        inner = obj.get("body")
        if isinstance(inner, str) and inner.strip():
            return inner, st, None
        return None, st, "render_service_missing_html_field"

    if "html" in ctype or text.lstrip().lower().startswith("<!doctype html") or "<html" in text[:2000].lower():
        return text, st, None

    return None, st, "unexpected_content_type"

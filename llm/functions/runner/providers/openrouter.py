"""OpenRouter via OpenAI-compatible HTTP API."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def _api_key() -> str | None:
    k = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    return k or None


def complete(
    *,
    model: str,
    messages: list[dict[str, Any]],
    response_format: str | None,
    provider_options: dict[str, Any] | None,
) -> tuple[dict[str, Any], int]:
    key = _api_key()
    if not key:
        return {"error": "OPENROUTER_API_KEY not configured", "provider": "openrouter"}, 503

    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
    }
    opts = provider_options or {}
    if isinstance(opts.get("temperature"), (int, float)):
        body["temperature"] = opts["temperature"]
    if response_format == "json":
        body["response_format"] = {"type": "json_object"}

    req = urllib.request.Request(
        OPENROUTER_URL,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
            "HTTP-Referer": "https://acs.local",
            "X-Title": "ACS LLM Service",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            raw = resp.read().decode("utf-8")
            data = json.loads(raw)
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8")
        try:
            detail = json.loads(err_body)
        except json.JSONDecodeError:
            detail = {"raw": err_body}
        return {"error": "openrouter_http_error", "status": e.code, "detail": detail, "provider": "openrouter"}, 502
    except OSError as e:
        return {"error": "openrouter_request_failed", "detail": str(e), "provider": "openrouter"}, 502

    try:
        choice0 = (data.get("choices") or [{}])[0]
        msg = choice0.get("message") or {}
        content = msg.get("content")
        if not isinstance(content, str):
            content = ""
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        out: dict[str, Any] = {"provider": "openrouter", "usage": usage}
        if response_format == "json":
            try:
                out["json"] = json.loads(content) if content else {}
            except json.JSONDecodeError:
                out["json"] = {"raw": content}
        else:
            out["text"] = content.strip()
        return out, 200
    except (KeyError, IndexError, TypeError) as e:
        return {"error": "openrouter_parse_error", "detail": str(e), "provider": "openrouter"}, 502

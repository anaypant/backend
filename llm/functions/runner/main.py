# LLM microservice: POST /llm/v1/complete (via internal API Gateway).

from __future__ import annotations

import json
from typing import Any

import functions_framework

import platform_auth
from providers.registry import get_provider


def _json_response(payload: dict, status: int):
    return (json.dumps(payload), status, {"Content-Type": "application/json"})


def _parse_messages(raw: Any) -> list[dict[str, Any]] | None:
    if not isinstance(raw, list) or not raw:
        return None
    out: list[dict[str, Any]] = []
    for m in raw:
        if not isinstance(m, dict):
            return None
        role = m.get("role")
        content = m.get("content")
        if not isinstance(role, str) or not isinstance(content, str):
            return None
        out.append({"role": role, "content": content})
    return out


@functions_framework.http
def main(request):
    if request.method != "POST":
        return _json_response({"error": "method not allowed"}, 405)

    ok, plat_err = platform_auth.verify_platform_caller(request)
    if not ok:
        return _json_response({"error": plat_err or "unauthorized"}, 401)

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _json_response({"error": "JSON object body required"}, 400)

    model = body.get("model")
    if not isinstance(model, str) or not model.strip():
        return _json_response({"error": "model is required"}, 400)

    messages = _parse_messages(body.get("messages"))
    if messages is None:
        return _json_response({"error": "messages must be a non-empty array of {role, content}"}, 400)

    provider_name = body.get("provider")
    if provider_name is not None and not isinstance(provider_name, str):
        return _json_response({"error": "provider must be a string when provided"}, 400)

    rf = body.get("response_format")
    if rf is not None and rf not in ("text", "json"):
        return _json_response({"error": "response_format must be text or json"}, 400)
    response_format: str | None = rf if isinstance(rf, str) else "text"

    provider_options = body.get("provider_options")
    if provider_options is not None and not isinstance(provider_options, dict):
        return _json_response({"error": "provider_options must be an object when provided"}, 400)

    fn = get_provider(provider_name if isinstance(provider_name, str) else None)
    if fn is None:
        return _json_response({"error": f"unknown provider: {provider_name!r}"}, 400)

    result, inner_status = fn(
        model=model.strip(),
        messages=messages,
        response_format=response_format,
        provider_options=provider_options if isinstance(provider_options, dict) else None,
    )
    http_status = 200 if inner_status < 400 else inner_status
    return _json_response(result, http_status)

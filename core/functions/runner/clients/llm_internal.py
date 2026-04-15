"""LLM internal API — POST /llm/v1/complete."""

from __future__ import annotations

import os
from typing import Any

from clients import gcp_identity
from clients.http_exec import post_json_with_bearer


def llm_origin() -> str:
    host = gcp_identity.normalize_internal_gateway_hostname(os.environ.get("LLM_INTERNAL_GATEWAY_HOSTNAME") or "")
    if not host:
        raise RuntimeError("LLM_INTERNAL_GATEWAY_HOSTNAME is not set")
    return f"https://{host}"


def complete(
    *,
    model: str,
    messages: list[dict[str, str]],
    provider: str = "openrouter",
    response_format: str | None = "text",
    provider_options: dict[str, Any] | None = None,
    timeout: int = 90,
) -> tuple[dict, int]:
    token = gcp_identity.id_token_for_llm_gateway()
    url = llm_origin().rstrip("/") + "/llm/v1/complete" + "/"
    payload: dict[str, Any] = {
        "provider": provider,
        "model": model,
        "messages": messages,
    }
    if response_format:
        payload["response_format"] = response_format
    if provider_options:
        payload["provider_options"] = provider_options
    return post_json_with_bearer(url, payload, bearer=token, timeout=timeout)

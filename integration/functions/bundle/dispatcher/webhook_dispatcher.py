"""Route ``POST /integrations/webhooks/v1/{provider}`` to the registered provider."""

from __future__ import annotations

from providers.provider_registry import PROVIDER_REGISTRY
from store.common import json_response


def handle_webhook_v1_request(request, provider_key: str):
    pk = (provider_key or "").strip().lower()
    provider = PROVIDER_REGISTRY.get(pk)
    if provider is None:
        return json_response({"error": "unknown provider", "provider": pk}, 404)
    handler = getattr(provider, "webhook_ingress", None)
    if handler is None:
        return json_response({"error": "webhook ingress not supported for provider", "provider": pk}, 501)
    return handler(request)

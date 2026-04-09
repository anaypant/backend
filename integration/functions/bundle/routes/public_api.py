from providers.provider_registry import PROVIDER_REGISTRY
from store.common import json_response


ROUTES = {
    "/integrations/followupboss/oauth/start": ("followupboss", "oauth_start", {"GET"}),
    "/integrations/followupboss/oauth/callback": ("followupboss", "oauth_callback", {"GET"}),
    "/integrations/followupboss/refresh": ("followupboss", "refresh", {"POST"}),
    "/integrations/followupboss/resync_webhooks": ("followupboss", "resync_webhooks", {"POST"}),
    "/integrations/followupboss/webhooks": ("followupboss", "list_webhooks", {"GET"}),
    "/integrations/followupboss/webhook_test": ("followupboss", "webhook_test", {"POST"}),
    "/integrations/followupboss/disconnect": ("followupboss", "disconnect", {"POST"}),
    "/integrations/webhooks/followupboss": ("followupboss", "webhook_ingress", {"POST"}),
}


def _route(path: str) -> tuple[str, str, set[str]] | None:
    p = (path or "").rstrip("/")
    for key, val in ROUTES.items():
        if p.endswith(key):
            return val
    return None


def handle_request(request):
    routed = _route(getattr(request, "path", "") or "")
    if not routed:
        return json_response({"error": "not found", "path": getattr(request, "path", "")}, 404)

    provider_key, handler_name, methods = routed
    if request.method not in methods:
        return json_response({"error": "method not allowed"}, 405)

    provider = PROVIDER_REGISTRY.get(provider_key)
    if provider is None:
        return json_response({"error": "provider not registered"}, 500)

    handler = getattr(provider, handler_name, None)
    if handler is None:
        return json_response({"error": "handler not implemented"}, 500)
    return handler(request)

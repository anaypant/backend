from providers.provider_registry import PROVIDER_REGISTRY
from store.browser_cors import cors_preflight_response, merge_cors_for_oauth_start_get
from store.common import json_response
from store.gcp_identity import SecretsOidcConfigError


ROUTES = {
    "/integrations/followupboss/oauth/start": ("followupboss", "oauth_start", {"GET"}),
    "/integrations/followupboss/status": ("followupboss", "connection_status", {"GET"}),
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
    path = getattr(request, "path", "") or ""
    pre = cors_preflight_response(request)
    if pre is not None:
        return pre

    routed = _route(path)
    if not routed:
        return json_response({"error": "not found", "path": path}, 404)

    provider_key, handler_name, methods = routed
    if request.method not in methods:
        return json_response({"error": "method not allowed"}, 405)

    provider = PROVIDER_REGISTRY.get(provider_key)
    if provider is None:
        return json_response({"error": "provider not registered"}, 500)

    handler = getattr(provider, handler_name, None)
    if handler is None:
        return json_response({"error": "handler not implemented"}, 500)
    try:
        out = handler(request)
    except SecretsOidcConfigError as e:
        out = json_response(e.payload, e.http_status)
    return merge_cors_for_oauth_start_get(request, out)

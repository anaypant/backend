from providers.provider_registry import PROVIDER_REGISTRY
from state_bridge.handlers import internal_state_from_providers, internal_state_to_providers
from store.browser_cors import cors_preflight_response, merge_cors_for_oauth_start_get
from store.common import json_response
from store.gcp_identity import SecretsOidcConfigError


_STATE_ROUTES: list[tuple[str, object, set[str]]] = [
    ("/integrations/internal/state/from_providers", internal_state_from_providers, {"POST"}),
    ("/integrations/internal/state/to_providers", internal_state_to_providers, {"POST"}),
]


def _route_state(path: str) -> tuple[object, set[str]] | None:
    p = (path or "").rstrip("/")
    for suffix, fn, methods in _STATE_ROUTES:
        if p.endswith(suffix):
            return fn, methods
    return None


ROUTES = {
    "/integrations/followupboss/oauth/start": ("followupboss", "oauth_start", {"GET"}),
    "/integrations/followupboss/status": ("followupboss", "connection_status", {"GET"}),
    "/integrations/followupboss/oauth/callback": ("followupboss", "oauth_callback", {"GET"}),
    "/integrations/followupboss/internal/webhook_sync": ("followupboss", "internal_webhook_sync", {"POST"}),
    "/integrations/followupboss/refresh": ("followupboss", "refresh", {"POST"}),
    "/integrations/followupboss/resync_webhooks": ("followupboss", "resync_webhooks", {"POST"}),
    "/integrations/followupboss/webhooks": ("followupboss", "list_webhooks", {"GET"}),
    "/integrations/followupboss/webhook_test": ("followupboss", "webhook_test", {"POST"}),
    "/integrations/followupboss/disconnect": ("followupboss", "disconnect", {"POST"}),
    "/integrations/followupboss/people/list": ("followupboss", "list_people_page", {"POST"}),
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

    state_r = _route_state(path)
    if state_r:
        fn, methods = state_r
        if request.method not in methods:
            return json_response({"error": "method not allowed"}, 405)
        try:
            out = fn(request)
        except SecretsOidcConfigError as e:
            out = json_response(e.payload, e.http_status)
        return merge_cors_for_oauth_start_get(request, out)

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

import os

"""Browser CORS for allowlisted SPA origins on selected integration paths."""

# (path suffix, HTTP methods that receive CORS response headers on success)
_CORS_ROUTES: tuple[tuple[str, frozenset[str]], ...] = (
    ("/integrations/followupboss/oauth/start", frozenset({"GET", "OPTIONS"})),
    ("/integrations/followupboss/disconnect", frozenset({"POST", "OPTIONS"})),
    ("/integrations/followupboss/status", frozenset({"GET", "OPTIONS"})),
)


def _allowed_origins() -> frozenset[str]:
    raw = (os.environ.get("ACS_BROWSER_CORS_ORIGINS") or "").strip()
    if not raw:
        return frozenset()
    parts = [p.strip().rstrip("/") for p in raw.split(",")]
    return frozenset(p for p in parts if p)


def _cors_route(path: str) -> tuple[str, frozenset[str]] | None:
    p = (path or "").rstrip("/")
    for suffix, methods in _CORS_ROUTES:
        if p.endswith(suffix.rstrip("/")):
            return suffix, methods
    return None


def cors_preflight_response(request) -> tuple[str, int, dict[str, str]] | None:
    """OPTIONS preflight for allowlisted paths and origins."""
    if request.method != "OPTIONS":
        return None
    matched = _cors_route(getattr(request, "path", "") or "")
    if not matched:
        return None
    _suffix, methods = matched
    allowed = _allowed_origins()
    if not allowed:
        return None
    origin = (request.headers.get("Origin") or "").strip().rstrip("/")
    if origin not in allowed:
        return ("", 403, {"Content-Type": "text/plain"})

    headers = {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Methods": ", ".join(sorted(methods)),
        "Access-Control-Allow-Headers": (
            "Authorization, Content-Type, X-Firebase-Authorization, X-Forwarded-Authorization, X-Requested-With"
        ),
        "Access-Control-Max-Age": "86400",
        "Vary": "Origin",
    }
    return ("", 204, headers)


def merge_browser_cors(request, response: tuple) -> tuple:
    """Attach Access-Control-Allow-Origin for GET/POST on allowlisted paths when Origin matches."""
    method = getattr(request, "method", "") or ""
    if method not in ("GET", "POST"):
        return response
    matched = _cors_route(getattr(request, "path", "") or "")
    if not matched:
        return response
    _suffix, methods = matched
    if method not in methods:
        return response
    allowed = _allowed_origins()
    if not allowed:
        return response
    origin = (request.headers.get("Origin") or "").strip().rstrip("/")
    if origin not in allowed:
        return response

    body, status, headers = response
    h = dict(headers)
    h["Access-Control-Allow-Origin"] = origin
    h["Vary"] = "Origin"
    return (body, status, h)


def merge_cors_for_oauth_start_get(request, response: tuple) -> tuple:
    """Backward-compatible name for merge_browser_cors."""
    return merge_browser_cors(request, response)

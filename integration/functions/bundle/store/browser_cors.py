import os

"""Browser CORS for GET /integrations/followupboss/oauth/start (OAuth SPA → public gateway)."""

_OAUTH_START_SUFFIX = "/integrations/followupboss/oauth/start"


def _allowed_origins() -> frozenset[str]:
    raw = (os.environ.get("ACS_BROWSER_CORS_ORIGINS") or "").strip()
    if not raw:
        return frozenset()
    parts = [p.strip().rstrip("/") for p in raw.split(",")]
    return frozenset(p for p in parts if p)


def _path_is_oauth_start(path: str) -> bool:
    p = (path or "").rstrip("/")
    return p.endswith(_OAUTH_START_SUFFIX.rstrip("/"))


def cors_preflight_response(request) -> tuple[str, int, dict[str, str]] | None:
    """If this is OPTIONS for oauth/start, return (body, status, headers) or None to ignore."""
    if request.method != "OPTIONS":
        return None
    if not _path_is_oauth_start(getattr(request, "path", "") or ""):
        return None
    allowed = _allowed_origins()
    if not allowed:
        return None
    origin = (request.headers.get("Origin") or "").strip().rstrip("/")
    if origin not in allowed:
        return ("", 403, {"Content-Type": "text/plain"})

    headers = {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Access-Control-Allow-Headers": (
            "Authorization, Content-Type, X-Firebase-Authorization, X-Requested-With"
        ),
        "Access-Control-Max-Age": "86400",
        "Vary": "Origin",
    }
    return ("", 204, headers)


def merge_cors_for_oauth_start_get(request, response: tuple) -> tuple:
    """Attach CORS headers to oauth/start GET when Origin is allowlisted."""
    if request.method != "GET":
        return response
    if not _path_is_oauth_start(getattr(request, "path", "") or ""):
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

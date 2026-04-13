"""Route public callback URLs to modular handlers."""

import json

from callbacks import followupboss_oauth


def dispatch(request):
    path = (getattr(request, "path", "") or "").rstrip("/")
    if path.endswith("/integrations/followupboss/oauth/callback") and request.method == "GET":
        return followupboss_oauth.handle(request)
    return (json.dumps({"error": "not found", "path": path}), 404, {"Content-Type": "application/json"})

import functions_framework

from handlers.health import handle_health
from handlers.publish import handle_publish


@functions_framework.http
def main(request):
    path = (getattr(request, "path", "") or "").rstrip("/") or "/"
    method = (request.method or "GET").upper()

    if path.endswith("/health") and method == "GET":
        return handle_health()
    if path.endswith("/events/v1/publish") and method == "POST":
        return handle_publish(request)
    return ('{"error":"not found"}', 404, {"Content-Type": "application/json"})

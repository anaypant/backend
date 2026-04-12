import functions_framework

from handlers import handle_delete, handle_read, handle_write, json_response


@functions_framework.http
def main(request):
    path = getattr(request, "path", "") or ""
    method = (request.method or "GET").upper()
    p = path.rstrip("/")

    if p.endswith("/health") and method == "GET":
        return json_response({"ok": True, "service": "secrets-bridge"}, 200)

    if p.endswith("/secrets/v1/write") and method == "POST":
        return handle_write(request)
    if p.endswith("/secrets/v1/read") and method == "POST":
        return handle_read(request)
    if p.endswith("/secrets/v1/delete") and method == "POST":
        return handle_delete(request)

    return json_response({"error": "not found", "path": path}, 404)

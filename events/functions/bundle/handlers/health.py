import json


def handle_health():
    return (json.dumps({"ok": True, "service": "events-bridge"}), 200, {"Content-Type": "application/json"})

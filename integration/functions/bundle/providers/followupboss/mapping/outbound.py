"""
ACS outbound action envelopes → FUB HTTP semantics.

Workflows emit ``metadata.outboundActions`` items ``{ "name", "payload" }``. ``egress.apply_outbound_actions``
already maps those names to ``FubClient`` calls. This module is the explicit documentation boundary and
thin adapter so inbound/outbound mapping stay symmetric under ``providers/followupboss/mapping/``.
"""

from __future__ import annotations

from typing import Any


def acs_outbound_action_to_fub_request(action: dict[str, Any]) -> dict[str, Any] | None:
    """
    Describe how an ACS outbound action maps to a FUB API shape (for tests and future non-HTTP transports).

    Returns a small serializable dict, or ``None`` if the action is invalid.
    """
    if not isinstance(action, dict):
        return None
    name = action.get("name")
    payload = action.get("payload") if isinstance(action.get("payload"), dict) else {}
    if not isinstance(name, str) or not name.strip():
        return None
    n = name.strip()
    if n == "upsertPerson":
        return {"fubOperation": "PUT/POST people", "body": dict(payload)}
    if n == "createNote":
        return {"fubOperation": "POST notes", "personId": payload.get("personId"), "body": payload.get("body")}
    if n == "createTask":
        return {"fubOperation": "POST tasks", "personId": payload.get("personId"), "body": payload.get("body")}
    return {"fubOperation": "unknown", "name": n}

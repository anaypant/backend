"""Volatile outbound apply (CRM) via integration-bridge when configured."""

from __future__ import annotations

from typing import Any

from clients import integration_bridge


def apply_followupboss_outbound(uid: str, actions: list[Any]) -> tuple[dict, int]:
    if not isinstance(uid, str) or not uid.strip():
        return {"error": "uid required"}, 400
    if not isinstance(actions, list) or not actions:
        return {"error": "actions must be a non-empty list"}, 400
    return integration_bridge.apply_followupboss_outbound(uid.strip(), actions)

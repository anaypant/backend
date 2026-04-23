"""
IntegrationWebhookEventV1-shaped payloads (see backend/contracts/integration_webhook_event.v1.json).

Inbound: verified provider webhook body → canonical envelope → ACSStateV1 shell via ``to_acs_state_v1``.
The ACS ``payload`` field remains the **raw provider webhook JSON** (FUB body) so core
``normalize_integration_payload`` can continue to interpret FUB shapes.
"""

from __future__ import annotations

import uuid
from typing import Any

_REQUIRED = frozenset({"provider", "eventId", "eventType", "connectionId", "payload"})


def build_canonical_webhook_event_v1(
    *,
    provider: str,
    connection_id: str,
    raw_provider_body: dict[str, Any],
) -> dict[str, Any]:
    """
    Build a dict matching IntegrationWebhookEventV1.

    ``raw_provider_body`` is the full parsed JSON object from the provider (e.g. FUB webhook body).
    """
    ev_id = raw_provider_body.get("eventId") if isinstance(raw_provider_body.get("eventId"), str) else None
    if not ev_id or not str(ev_id).strip():
        ev_id = str(uuid.uuid4())
    ev_type = raw_provider_body.get("event") if isinstance(raw_provider_body.get("event"), str) else "unknown"
    return {
        "provider": (provider or "").strip().lower(),
        "eventId": str(ev_id).strip(),
        "eventType": str(ev_type).strip() or "unknown",
        "connectionId": connection_id,
        "payload": raw_provider_body,
    }


def validate_canonical_webhook_event_v1(obj: dict[str, Any]) -> tuple[bool, str | None]:
    """Lightweight structural check (no jsonschema dependency)."""
    if not isinstance(obj, dict):
        return False, "not_an_object"
    for k in _REQUIRED:
        if k not in obj:
            return False, f"missing:{k}"
    if not isinstance(obj.get("payload"), dict):
        return False, "payload_not_object"
    return True, None


def to_acs_state_v1(canonical: dict[str, Any], *, connection_id: str) -> dict[str, Any]:
    """
    Map canonical IntegrationWebhookEventV1 → ACSStateV1 dict.

    ``payload`` is ``canonical["payload"]`` (raw provider body). ``correlation_id`` uses ``eventId``.
    """
    ok, err = validate_canonical_webhook_event_v1(canonical)
    if not ok:
        raise ValueError(f"invalid canonical webhook event: {err}")

    provider = canonical["provider"]
    event_type = canonical["eventType"]
    correlation = canonical["eventId"]
    payload = canonical["payload"]
    if not isinstance(payload, dict):
        raise ValueError("canonical payload must be dict")

    return {
        "state_version": 1,
        "correlation_id": correlation,
        "tenant_id": None,
        "user_id": connection_id,
        "source": {"provider": provider, "event_type": event_type},
        "payload": dict(payload),
        "metadata": {
            "connection_id": connection_id,
            "canonical_webhook": {
                "provider": provider,
                "eventId": correlation,
                "eventType": event_type,
            },
        },
    }

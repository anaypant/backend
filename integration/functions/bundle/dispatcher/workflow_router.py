"""Resolve default ``workflow_id`` from FUB event type and execution policy (extensible)."""

from __future__ import annotations

# FUB webhook events use camelCase. These carry a person ``uri`` that ``normalize_contact`` maps to
# ``external_person_id`` for ``contact.enrichment_v1`` (see core ``normalize_integration_payload``).
_DEFAULT_ENRICHMENT_EVENTS: frozenset[str] = frozenset(
    {
        "peopleCreated",
        "peopleUpdated",
    }
)


def resolve_default_workflow_id(event_type: str, policy: dict) -> str | None:
    """
    When no explicit ``workflowId`` query param is provided, return a default core workflow id.

    Unknown event types return ``None`` so core runs its stub handler (no-op) until wired.
    """
    et = (event_type or "").strip()
    if et in _DEFAULT_ENRICHMENT_EVENTS:
        return "contact.enrichment_v1"
    _ = policy
    return None

"""Resolve default ``workflow_id`` from FUB event type and execution policy (extensible)."""

from __future__ import annotations


def resolve_default_workflow_id(event_type: str, policy: dict) -> str | None:
    """
    When no explicit ``workflowId`` query param is provided, return a default core workflow id.

    Returns ``None`` to run the core stub handler until product routes are configured per event type.
    """
    _ = event_type, policy
    return None

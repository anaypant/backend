"""
Declarative mapping: (provider, webhook event type) → ordered list of core ``workflow_id`` strings.

Explicit ``workflowId`` query param (testing) overrides this table and yields a single-element list.
"""

from __future__ import annotations

import re
from typing import Any

# Keys: normalized lookup token (lowercase, underscores). Values: workflow ids in run order.
_FUB_EVENT_TO_WORKFLOWS: dict[str, list[str]] = {
    "peoplecreated": ["contact.enrichment_v1"],
    "peopleupdated": ["contact.enrichment_v1"],
}


def event_type_alias_keys(event_type: str | None) -> list[str]:
    """Return lookup keys for event_type (e.g. peopleCreated, people_created)."""
    if not event_type or not isinstance(event_type, str):
        return []
    et = event_type.strip()
    if not et:
        return []
    out: list[str] = [et]
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", et).lower()
    if snake not in out:
        out.append(snake)
    if "_" in snake:
        parts = snake.split("_")
        camel = "".join(w.capitalize() if i else w for i, w in enumerate(parts))
        if camel not in out:
            out.append(camel)
    return out


def _normalized_map_keys_for_provider(provider: str) -> dict[str, list[str]] | None:
    p = (provider or "").strip().lower()
    if p == "followupboss":
        return _FUB_EVENT_TO_WORKFLOWS
    return None


def _event_type_normal_key(s: str) -> str:
    """``peopleCreated`` / ``people_created`` / ``PeopleCreated`` → ``peoplecreated``."""
    t = (s or "").strip().lower().replace("-", "_")
    return "".join(t.split("_"))


def resolve_workflow_ids_for_webhook(
    provider: str,
    event_type: str,
    *,
    explicit_workflow_id: str | None,
    policy: dict[str, Any] | None = None,
) -> list[str]:
    """
    Resolve which core workflows should run for this webhook.

    If ``explicit_workflow_id`` is non-empty, returns ``[that id]`` only.
    Otherwise looks up ``provider`` + ``event_type`` (with aliases). Unknown → ``[]``.
    """
    _ = policy
    ex = (explicit_workflow_id or "").strip()
    if ex:
        return [ex]
    table = _normalized_map_keys_for_provider(provider)
    if not table:
        return []
    seen: set[str] = set()
    for key in event_type_alias_keys(event_type):
        nk = _event_type_normal_key(key)
        if nk in seen:
            continue
        seen.add(nk)
        mapped = table.get(nk)
        if mapped:
            return list(mapped)
    return []


def resolve_default_workflow_id(event_type: str, policy: dict) -> str | None:
    """Backward-compatible single default (first mapped workflow, or None)."""
    ids = resolve_workflow_ids_for_webhook("followupboss", event_type, explicit_workflow_id=None, policy=policy)
    return ids[0] if ids else None

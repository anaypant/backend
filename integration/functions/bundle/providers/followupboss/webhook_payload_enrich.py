"""Enrich FUB webhook JSON before forwarding to core (integration has CRM tokens)."""

from __future__ import annotations

from typing import Any

from providers.followupboss.client import FubClient


def merge_fub_person_from_api(connection_id: str, fub: dict, payload: dict[str, Any]) -> dict[str, Any] | None:
    """
    If ``payload`` is a people-related webhook with ``uri``, GET the resource and set ``fubPerson``.

    Mutates ``payload`` in place. Returns ``{"http": int}`` for observability, or ``None`` if skipped.
    """
    if not isinstance(payload, dict):
        return None
    if isinstance(payload.get("fubPerson"), dict):
        return None
    ev = payload.get("event") if isinstance(payload.get("event"), str) else ""
    if not ev.startswith("people"):
        return None
    uri = payload.get("uri")
    if not isinstance(uri, str) or not uri.strip():
        return None

    auth = dict(fub.get("auth") or {})
    client = FubClient(
        access_token_ref=auth.get("accessTokenRef"),
        api_key_ref=auth.get("apiKeyRef"),
        acting_uid=connection_id,
    )
    body, st = client.get_by_uri(uri.strip())
    if st < 400 and isinstance(body, dict):
        payload["fubPerson"] = body
    return {"http": st}

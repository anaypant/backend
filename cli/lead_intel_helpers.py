"""
Helpers for lead-intelligence CLI / tests.

``internal_client_doc_id`` must stay aligned with
``backend/core/functions/runner/workflows/normalize_integration_payload.internal_client_doc_id``.
"""

from __future__ import annotations

import re
import uuid
from typing import Any


def internal_client_doc_id(*, provider: str, external_person_id: str | int) -> str:
    prov = str(provider or "unknown").replace("/", "_")[:40]
    ext = str(external_person_id or "unknown").replace("/", "_")[:80]
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", f"{prov}_{ext}").strip("_")[:128]
    return safe or "unknown"


def canonical_lead_doc_id(person_id: int) -> str:
    """``Realtors/{uid}/Leads/{id}`` id segment for FUB (matches lead_internal_v1.canonical_lead_id)."""
    return internal_client_doc_id(provider="followupboss", external_person_id=str(int(person_id)))


def fub_webhook_minimal_body(
    *,
    event: str,
    person_id: int,
    event_id: str | None = None,
) -> dict[str, Any]:
    """
    Minimal FUB-shaped webhook JSON (integration hydrates person via API when possible).

    ``event`` should be ``peopleCreated`` or ``peopleUpdated`` (see ``normalize_fub_webhook_event``).
    """
    eid = event_id if (event_id and str(event_id).strip()) else f"cli-{uuid.uuid4().hex[:16]}"
    uri = f"https://api.followupboss.com/v1/people?id={int(person_id)}"
    return {
        "eventId": eid,
        "event": event,
        "resourceIds": [int(person_id)],
        "uri": uri,
    }


# Aliases users type; values are canonical FUB event strings on the wire.
_FUB_EVENT_ALIASES: dict[str, str] = {
    "personcreated": "peopleCreated",
    "personupdated": "peopleUpdated",
    "peoplecreated": "peopleCreated",
    "peopleupdated": "peopleUpdated",
    "people_created": "peopleCreated",
    "people_updated": "peopleUpdated",
}


def normalize_fub_webhook_event(event: str) -> str:
    k = (event or "").strip()
    if not k:
        return "peopleCreated"
    nk = "".join(k.lower().replace("-", "_").split("_"))
    return _FUB_EVENT_ALIASES.get(nk, k)

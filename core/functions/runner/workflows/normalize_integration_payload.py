"""Map integration-specific webhook payloads into InternalContactV1-shaped dicts."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlparse

_URI_PERSON_RE = re.compile(r"/people/(\d+)\s*$", re.IGNORECASE)


def _fub_person_id_from_resource_ids(payload: dict[str, Any]) -> int | None:
    ri = payload.get("resourceIds")
    if not isinstance(ri, list):
        return None
    for x in ri:
        if isinstance(x, int) and x > 0:
            return x
        if isinstance(x, str) and x.strip().isdigit():
            return int(x.strip())
    return None


def _fub_person_id_from_uri(uri: str | None) -> int | None:
    """Resolve FUB person id from webhook ``uri`` (path or query style)."""
    if not isinstance(uri, str) or not uri.strip():
        return None
    s = uri.strip()
    m = _URI_PERSON_RE.search(s)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    # e.g. https://api.followupboss.com/v1/people?id=1 (see FUB docs / lite sample payloads)
    try:
        parsed = urlparse(s)
        path_l = (parsed.path or "").lower()
        if "people" not in path_l:
            return None
        qs = parse_qs(parsed.query)
        for key in ("id", "personId", "person_id"):
            vals = qs.get(key)
            if not vals:
                continue
            raw = str(vals[0]).strip()
            if raw.isdigit():
                v = int(raw)
                return v if v > 0 else None
    except (TypeError, ValueError):
        return None
    return None


def _resolve_fub_person_id(payload: dict[str, Any]) -> int | None:
    uri = payload.get("uri") if isinstance(payload.get("uri"), str) else None
    pid = _fub_person_id_from_uri(uri)
    if pid is not None:
        return pid
    return _fub_person_id_from_resource_ids(payload)


def normalize_contact(acs: dict) -> dict[str, Any]:
    """
    InternalContactV1 (informal contract):

    - provider (str)
    - external_person_id (str | int)
    - display_name (str)
    - emails (list[str])
    - phones (list[str])
    - person_id (int | None)  # CRM-native id when known
    - raw (dict)  # subset of original payload for debugging
    """
    src = acs.get("source") if isinstance(acs.get("source"), dict) else {}
    provider = src.get("provider") if isinstance(src.get("provider"), str) else "unknown"
    payload = acs.get("payload") if isinstance(acs.get("payload"), dict) else {}

    if provider == "followupboss":
        uri = payload.get("uri") if isinstance(payload.get("uri"), str) else None
        pid = _resolve_fub_person_id(payload if isinstance(payload, dict) else {})
        event_type = payload.get("event") if isinstance(payload.get("event"), str) else ""
        return {
            "provider": "followupboss",
            "external_person_id": str(pid) if pid is not None else "",
            "display_name": "",
            "emails": [],
            "phones": [],
            "person_id": pid,
            "event_type": event_type,
            "raw": {"uri": uri, "event": event_type, "eventId": payload.get("eventId")},
        }

    # Generic passthrough for future providers
    ext = payload.get("id") or payload.get("externalId") or payload.get("contactId") or ""
    return {
        "provider": provider,
        "external_person_id": str(ext) if ext is not None else "",
        "display_name": str(payload.get("name") or "")[:500],
        "emails": [],
        "phones": [],
        "person_id": None,
        "event_type": str(src.get("event_type") or "")[:200],
        "raw": {"keys": list(payload.keys())[:40]},
    }


def internal_client_doc_id(normalized: dict[str, Any]) -> str:
    """Stable Firestore document id under Realtors/{uid}/InternalClients/{id}."""
    prov = str(normalized.get("provider") or "unknown").replace("/", "_")[:40]
    ext = str(normalized.get("external_person_id") or "unknown").replace("/", "_")[:80]
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", f"{prov}_{ext}").strip("_")[:128]
    return safe or "unknown"

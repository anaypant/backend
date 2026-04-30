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


def _fub_display_name(person: dict[str, Any]) -> str:
    fn = person.get("firstName") if isinstance(person.get("firstName"), str) else ""
    ln = person.get("lastName") if isinstance(person.get("lastName"), str) else ""
    parts = f"{fn} {ln}".strip()
    if parts:
        return parts[:500]
    name = person.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()[:500]
    pid = person.get("id")
    if isinstance(pid, int):
        return f"person {pid}"
    return ""


def _fub_emails(person: dict[str, Any]) -> list[str]:
    out: list[str] = []
    raw = person.get("emails")
    if not isinstance(raw, list):
        return out
    for e in raw[:30]:
        if not isinstance(e, dict):
            continue
        v = e.get("value") if isinstance(e.get("value"), str) else None
        if v and v.strip():
            out.append(v.strip()[:320])
            continue
        ev = e.get("email") if isinstance(e.get("email"), str) else None
        if ev and ev.strip():
            out.append(ev.strip()[:320])
    return out[:20]


def _fub_phones(person: dict[str, Any]) -> list[str]:
    out: list[str] = []
    raw = person.get("phones")
    if not isinstance(raw, list):
        return out
    for p in raw[:30]:
        if not isinstance(p, dict):
            continue
        v = p.get("value") if isinstance(p.get("value"), str) else None
        if v and v.strip():
            out.append(v.strip()[:40])
    return out[:20]


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
        # Accept both the webhook-enriched key (fubPerson) and direct API call key (person).
        fp = payload.get("fubPerson") or payload.get("person")
        display_name = ""
        emails: list[str] = []
        phones: list[str] = []
        if isinstance(fp, dict):
            display_name = _fub_display_name(fp)
            emails = _fub_emails(fp)
            phones = _fub_phones(fp)
            fp_id = fp.get("id")
            if isinstance(fp_id, int) and fp_id > 0:
                pid = fp_id
            # Resolve person_id from resourceIds / uri if not already found.
            if pid is None:
                pid = _resolve_fub_person_id(fp)
        return {
            "provider": "followupboss",
            "external_person_id": str(pid) if pid is not None else "",
            "display_name": display_name[:500],
            "emails": emails[:20],
            "phones": phones[:20],
            "person_id": pid,
            "event_type": event_type,
            "raw": {
                "uri": uri,
                "event": event_type,
                "eventId": payload.get("eventId"),
                "has_fub_person": isinstance(fp, dict),
            },
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

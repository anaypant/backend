"""
Follow Up Boss ``person`` resource ↔ internal lead (v1).

Inbound: FUB GET /people rows. Outbound: FUB POST /people-style payload subset.
https://docs.followupboss.com/reference/people-get
"""

from __future__ import annotations

from typing import Any

from workflows.migrations.schemas.lead_internal_v1 import canonical_lead_id, empty_internal_lead

_PROVIDER = "followupboss"


def _first_email_value(emails: Any) -> str | None:
    if not isinstance(emails, list):
        return None
    for e in emails:
        if isinstance(e, dict):
            v = e.get("value")
            if isinstance(v, str) and v.strip():
                return v.strip()
        elif isinstance(e, str) and e.strip():
            return e.strip()
    return None


def _first_phone_value(phones: Any) -> str | None:
    if not isinstance(phones, list):
        return None
    for p in phones:
        if isinstance(p, dict):
            v = p.get("value") or p.get("number")
            if isinstance(v, str) and v.strip():
                return v.strip()
        elif isinstance(p, str) and p.strip():
            return p.strip()
    return None


def _normalize_email_list(emails: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not isinstance(emails, list):
        return out
    for i, e in enumerate(emails[:25]):
        if isinstance(e, dict):
            val = e.get("value")
            if isinstance(val, str) and val.strip():
                out.append(
                    {
                        "value": val.strip()[:320],
                        "type": str(e.get("type") or "")[:64],
                        "isPrimary": bool(e.get("isPrimary")) if "isPrimary" in e else i == 0,
                    }
                )
        elif isinstance(e, str) and e.strip():
            out.append({"value": e.strip()[:320], "type": "", "isPrimary": i == 0})
    return out


def _normalize_phone_list(phones: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not isinstance(phones, list):
        return out
    for i, p in enumerate(phones[:25]):
        if isinstance(p, dict):
            val = p.get("value") or p.get("number")
            if isinstance(val, str) and val.strip():
                out.append(
                    {
                        "value": val.strip()[:40],
                        "type": str(p.get("type") or "")[:64],
                        "isPrimary": bool(p.get("isPrimary")) if "isPrimary" in p else i == 0,
                    }
                )
        elif isinstance(p, str) and p.strip():
            out.append({"value": p.strip()[:40], "type": "", "isPrimary": i == 0})
    return out


def _tags_as_strings(tags: Any) -> list[str]:
    if not isinstance(tags, list):
        return []
    out: list[str] = []
    for t in tags[:40]:
        if isinstance(t, dict):
            n = t.get("name") or t.get("tag")
            if isinstance(n, str) and n.strip():
                out.append(n.strip()[:120])
        elif isinstance(t, str) and t.strip():
            out.append(t.strip()[:120])
    return out


def followupboss_person_to_internal(person: dict[str, Any]) -> dict[str, Any] | None:
    """Map one FUB ``person`` object to ``lead_internal_v1``."""
    pid = person.get("id")
    if not isinstance(pid, int):
        return None
    ext = str(pid)
    fn = person.get("firstName") if isinstance(person.get("firstName"), str) else ""
    ln = person.get("lastName") if isinstance(person.get("lastName"), str) else ""
    display = (f"{fn} {ln}").strip() or (person.get("name") if isinstance(person.get("name"), str) else "") or ext

    emails = _normalize_email_list(person.get("emails"))
    phones = _normalize_phone_list(person.get("phones"))

    stage = person.get("stage")
    stage_label = None
    if isinstance(stage, dict):
        stage_label = stage.get("name") if isinstance(stage.get("name"), str) else None
    elif isinstance(stage, str):
        stage_label = stage

    src = person.get("source")
    src_label = None
    if isinstance(src, dict):
        src_label = src.get("name") if isinstance(src.get("name"), str) else None
    elif isinstance(src, str):
        src_label = src

    internal = empty_internal_lead()
    internal["canonicalLeadId"] = canonical_lead_id(_PROVIDER, ext)
    internal["sourceProvider"] = _PROVIDER
    internal["externalId"] = ext
    internal["displayName"] = display[:500]
    internal["givenName"] = fn[:200]
    internal["familyName"] = ln[:200]
    internal["primaryEmail"] = _first_email_value(person.get("emails"))
    internal["primaryPhone"] = _first_phone_value(person.get("phones"))
    internal["emails"] = emails
    internal["phones"] = phones
    internal["stageLabel"] = str(stage_label)[:200] if stage_label else None
    internal["sourceLabel"] = str(src_label)[:200] if src_label else None
    internal["tags"] = _tags_as_strings(person.get("tags"))
    # Bounded echo for debugging / future round-trip (strip huge graphs)
    keep = (
        "id",
        "created",
        "updated",
        "assignedTo",
        "status",
        "price",
        "timeframe",
        "dealStatus",
        "collaborators",
    )
    echo: dict[str, Any] = {k: person[k] for k in keep if k in person}
    internal["providerPayload"] = echo
    return internal


def internal_to_followupboss_person_upsert(internal: dict[str, Any]) -> dict[str, Any]:
    """
    Map internal lead v1 → FUB ``POST /v1/people`` body subset (merge-style fields).

    Does not set ``id`` (create); for updates caller should use person id separately.
    """
    out: dict[str, Any] = {}
    gn = internal.get("givenName")
    if isinstance(gn, str) and gn.strip():
        out["firstName"] = gn.strip()[:200]
    fn = internal.get("familyName")
    if isinstance(fn, str) and fn.strip():
        out["lastName"] = fn.strip()[:200]

    emails_in = internal.get("emails")
    if isinstance(emails_in, list) and emails_in:
        fub_emails: list[dict[str, Any]] = []
        for e in emails_in[:15]:
            if not isinstance(e, dict):
                continue
            v = e.get("value")
            if isinstance(v, str) and v.strip():
                row: dict[str, Any] = {"value": v.strip()[:320]}
                t = e.get("type")
                if isinstance(t, str) and t.strip():
                    row["type"] = t.strip()[:64]
                if "isPrimary" in e:
                    row["isPrimary"] = bool(e.get("isPrimary"))
                fub_emails.append(row)
        if fub_emails:
            out["emails"] = fub_emails

    phones_in = internal.get("phones")
    if isinstance(phones_in, list) and phones_in:
        fub_phones: list[dict[str, Any]] = []
        for p in phones_in[:15]:
            if not isinstance(p, dict):
                continue
            v = p.get("value")
            if isinstance(v, str) and v.strip():
                row = {"value": v.strip()[:40]}
                t = p.get("type")
                if isinstance(t, str) and t.strip():
                    row["type"] = t.strip()[:64]
                if "isPrimary" in p:
                    row["isPrimary"] = bool(p.get("isPrimary"))
                fub_phones.append(row)
        if fub_phones:
            out["phones"] = fub_phones

    tags_in = internal.get("tags")
    if isinstance(tags_in, list) and tags_in:
        out["tags"] = [{"name": str(t)[:120]} for t in tags_in if isinstance(t, str) and t.strip()][:40]

    sl = internal.get("stageLabel")
    if isinstance(sl, str) and sl.strip():
        out["stage"] = {"name": sl.strip()[:200]}

    src = internal.get("sourceLabel")
    if isinstance(src, str) and src.strip():
        out["source"] = {"name": src.strip()[:200]}

    return out


def internal_to_followupboss_person_id(internal: dict[str, Any]) -> int | None:
    """Return FUB integer person id when ``sourceProvider`` is followupboss."""
    if internal.get("sourceProvider") != _PROVIDER:
        return None
    ext = internal.get("externalId")
    if isinstance(ext, str) and ext.strip().isdigit():
        return int(ext.strip())
    return None

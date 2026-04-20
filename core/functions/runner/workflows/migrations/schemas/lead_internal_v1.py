"""ACS internal lead envelope (provider-agnostic). Version 1."""

from __future__ import annotations

LEAD_INTERNAL_SCHEMA_VERSION = 1


def canonical_lead_id(source_provider: str, external_id: str) -> str:
    """Stable document id segment under ``Realtors/{uid}/Leads/{id}`` (matches enrichment index style)."""
    prov = (source_provider or "unknown").replace("/", "_").strip()[:40] or "unknown"
    ext = str(external_id or "").replace("/", "_").strip()[:80] or "unknown"
    return f"{prov}_{ext}"


def empty_internal_lead() -> dict:
    return {
        "schemaVersion": LEAD_INTERNAL_SCHEMA_VERSION,
        "canonicalLeadId": "",
        "sourceProvider": "",
        "externalId": "",
        "displayName": "",
        "givenName": "",
        "familyName": "",
        "primaryEmail": None,
        "primaryPhone": None,
        "emails": [],
        "phones": [],
        "stageLabel": None,
        "sourceLabel": None,
        "tags": [],
        "providerPayload": {},
    }

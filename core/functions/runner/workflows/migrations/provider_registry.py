"""Dispatch raw CRM rows → internal lead by ``sourceProvider``."""

from __future__ import annotations

from typing import Any

from workflows.migrations.provider_maps import followupboss_lead


def raw_record_to_internal(provider: str, record: dict[str, Any]) -> dict[str, Any] | None:
    p = (provider or "").strip().lower()
    if p == "followupboss":
        return followupboss_lead.followupboss_person_to_internal(record)
    return None


def internal_to_provider_upsert_payload(provider: str, internal: dict[str, Any]) -> dict[str, Any] | None:
    """Outbound field bundle for the given provider (e.g. FUB POST /people body)."""
    p = (provider or "").strip().lower()
    if p == "followupboss":
        return followupboss_lead.internal_to_followupboss_person_upsert(internal)
    return None


def internal_to_provider_external_id(provider: str, internal: dict[str, Any]) -> int | str | None:
    p = (provider or "").strip().lower()
    if p == "followupboss":
        return followupboss_lead.internal_to_followupboss_person_id(internal)
    return internal.get("externalId")

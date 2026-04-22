"""Shared Follow Up Boss ``GET /v1/people`` fetch for HTTP handlers."""

from __future__ import annotations

from typing import Any

from providers.followupboss.client import FubClient
from store.profile_repo import fub_config_from_profile, load_realtor_profile


def fetch_people_page(
    uid: str,
    *,
    batch_size: int = 50,
    offset: int | None = None,
    next_token: str | None = None,
) -> tuple[dict[str, Any], int | None]:
    """
    Returns ``({"people": [...], "_metadata": {...}}, None)`` on success, or
    ``({}, http_status)`` on failure (profile, config, or FUB API).
    """
    uid = uid.strip()
    if not uid:
        return {}, 400

    lim = max(1, min(100, int(batch_size)))

    profile, st = load_realtor_profile(uid)
    if st not in (200, 404) or not isinstance(profile, dict):
        return {"error": "profile_load_failed", "httpStatus": st}, st
    fub = fub_config_from_profile(profile)
    if not fub:
        return {"error": "followupboss_not_configured"}, 404

    auth = dict(fub.get("auth") or {})
    client = FubClient(
        access_token_ref=auth.get("accessTokenRef"),
        api_key_ref=auth.get("apiKeyRef"),
        acting_uid=uid,
    )

    fub_body, fub_st = client.list_people(limit=lim, offset=offset, next_token=next_token)
    if fub_st >= 400:
        return {"error": "followupboss_people_list_failed", "httpStatus": fub_st, "detail": fub_body}, fub_st

    body = fub_body if isinstance(fub_body, dict) else {}
    people = body.get("people") if isinstance(body.get("people"), list) else []
    meta = body.get("_metadata") if isinstance(body.get("_metadata"), dict) else {}
    return {"people": people, "_metadata": meta}, None


def parse_list_request(payload: dict[str, Any]) -> tuple[int, int | None, str | None]:
    """From JSON body: batch_size, offset, next_token."""
    batch_raw = payload.get("batchSize", payload.get("limit"))
    try:
        batch_size = int(batch_raw) if batch_raw is not None else 50
    except (TypeError, ValueError):
        batch_size = 50
    batch_size = max(1, min(100, batch_size))

    nt = payload.get("next")
    if isinstance(nt, str) and nt.strip():
        return batch_size, None, nt.strip()

    off_raw = payload.get("offset")
    try:
        offset = int(off_raw) if off_raw is not None else 0
    except (TypeError, ValueError):
        offset = 0
    return batch_size, max(0, offset), None


def fetch_person_by_id(uid: str, person_id: int) -> tuple[dict[str, Any] | None, int | None]:
    """
    GET /v1/people/{id} for one person.

    Returns ``(person_dict, None)`` on success, or ``(None, http_status)`` on failure.
    """
    uid = uid.strip()
    if not uid:
        return None, 400
    if not isinstance(person_id, int) or person_id <= 0:
        return None, 400

    profile, st = load_realtor_profile(uid)
    if st not in (200, 404) or not isinstance(profile, dict):
        return None, st
    fub = fub_config_from_profile(profile)
    if not fub:
        return None, 404

    auth = dict(fub.get("auth") or {})
    client = FubClient(
        access_token_ref=auth.get("accessTokenRef"),
        api_key_ref=auth.get("apiKeyRef"),
        acting_uid=uid,
    )
    body, fub_st = client.get_person(person_id)
    if fub_st >= 400:
        return None, fub_st
    if not isinstance(body, dict):
        return None, 502
    return body, None

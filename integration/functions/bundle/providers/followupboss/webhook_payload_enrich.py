"""Enrich FUB webhook JSON before forwarding to core (integration has CRM tokens)."""

from __future__ import annotations

import logging
from typing import Any

from providers.followupboss.client import FubClient
from providers.followupboss.fub_payload_person_id import person_id_from_fub_webhook_payload

_logger = logging.getLogger(__name__)


def merge_fub_person_from_api(connection_id: str, fub: dict, payload: dict[str, Any]) -> dict[str, Any] | None:
    """
    For people-related webhooks, GET the person and set ``fubPerson`` on ``payload``.

    Tries ``GET uri`` first when present, then ``GET /v1/people/{id}`` from parsed id / ``resourceIds``.

    Mutates ``payload`` in place. Returns a small status dict for logs, or ``None`` if skipped.
    """
    if not isinstance(payload, dict):
        return None
    if isinstance(payload.get("fubPerson"), dict):
        return None
    ev = payload.get("event") if isinstance(payload.get("event"), str) else ""
    if not ev.startswith("people"):
        return None

    auth = dict(fub.get("auth") or {})
    client = FubClient(
        access_token_ref=auth.get("accessTokenRef"),
        api_key_ref=auth.get("apiKeyRef"),
        acting_uid=connection_id,
    )

    uri = payload.get("uri")
    if isinstance(uri, str) and uri.strip():
        body, st = client.get_by_uri(uri.strip())
        if st < 400 and isinstance(body, dict):
            payload["fubPerson"] = body
            _logger.info(
                "fub_webhook_enrich ok via=uri connection_id=%s event=%s http=%s",
                connection_id,
                ev,
                st,
            )
            return {"http": st, "via": "uri"}
        _logger.info(
            "fub_webhook_enrich uri_fetch_failed connection_id=%s event=%s http=%s",
            connection_id,
            ev,
            st,
        )

    pid = person_id_from_fub_webhook_payload(payload)
    if isinstance(pid, int) and pid > 0:
        body2, st2 = client.get_person(pid)
        if st2 < 400 and isinstance(body2, dict):
            payload["fubPerson"] = body2
            _logger.info(
                "fub_webhook_enrich ok via=person_id connection_id=%s event=%s person_id=%s http=%s",
                connection_id,
                ev,
                pid,
                st2,
            )
            return {"http": st2, "via": "person_id"}
        _logger.info(
            "fub_webhook_enrich person_fetch_failed connection_id=%s event=%s person_id=%s http=%s",
            connection_id,
            ev,
            pid,
            st2,
        )
        return {"http": st2, "via": "person_id_failed"}

    _logger.info(
        "fub_webhook_enrich skipped_no_person_ref connection_id=%s event=%s keys=%s",
        connection_id,
        ev,
        list(payload.keys())[:12],
    )
    return None

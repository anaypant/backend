"""Enrich FUB webhook JSON before forwarding to core (integration has CRM tokens)."""

from __future__ import annotations

import logging
from typing import Any

from providers.followupboss.client import FubClient
from providers.followupboss.fub_payload_person_id import person_id_from_fub_webhook_payload

_logger = logging.getLogger(__name__)


def _coerce_fub_person_record(body: Any) -> dict[str, Any] | None:
    """FUB sometimes wraps the person in ``person``; list endpoints may nest differently."""
    if not isinstance(body, dict):
        return None
    inner = body.get("person")
    if isinstance(inner, dict) and (inner.get("id") is not None or inner.get("firstName") is not None):
        return inner
    if body.get("id") is not None or body.get("firstName") is not None or body.get("name") is not None:
        return body
    return None


def _fub_client(connection_id: str, fub: dict) -> FubClient:
    auth = dict(fub.get("auth") or {})
    return FubClient(
        access_token_ref=auth.get("accessTokenRef"),
        api_key_ref=auth.get("apiKeyRef"),
        acting_uid=connection_id,
    )


def merge_fub_person_from_api(connection_id: str, fub: dict, payload: dict[str, Any]) -> dict[str, Any]:
    """
    For people-related webhooks, GET the person and set ``fubPerson`` on ``payload``.

    Tries ``GET uri`` first when present, then ``GET /v1/people/{id}``. On **401**, runs one OAuth
    refresh (same as ``/integrations/followupboss/refresh``) and retries the same fetch once.

    Mutates ``payload`` in place. Always returns a **dict** for ``metadata.integrationEnrich`` on core.
    """
    out: dict[str, Any] = {"fubPersonSet": False, "skipped": None, "oauthRefreshed": False, "oauth_refresh_http": None}

    if not isinstance(payload, dict):
        out["skipped"] = "not_a_dict"
        return out
    if isinstance(payload.get("fubPerson"), dict):
        out["skipped"] = "already_present"
        out["fubPersonSet"] = True
        return out
    ev = payload.get("event") if isinstance(payload.get("event"), str) else ""
    if not str(ev).lower().startswith("people"):
        out["skipped"] = "not_people_event"
        out["event"] = ev
        return out

    from providers.followupboss import oauth as fub_oauth

    refresh_attempted = False

    def _refresh() -> bool:
        """At most one refresh per webhook (covers expired access token before retrying FUB GET)."""
        nonlocal refresh_attempted
        if refresh_attempted:
            return False
        refresh_attempted = True
        rb, rst = fub_oauth.refresh_fub_oauth_tokens_for_uid(connection_id)
        out["oauth_refresh_http"] = rst
        ok = rst < 400
        out["oauthRefreshed"] = ok
        if ok:
            _logger.warning(
                "fub_webhook_enrich oauth_refreshed connection_id=%s event=%s http=%s",
                connection_id,
                ev,
                rst,
            )
        else:
            _logger.warning(
                "fub_webhook_enrich oauth_refresh_failed connection_id=%s event=%s http=%s detail=%s",
                connection_id,
                ev,
                rst,
                str(rb)[:300] if isinstance(rb, dict) else rb,
            )
        return ok

    uri = payload.get("uri")
    if isinstance(uri, str) and uri.strip():
        u = uri.strip()
        client = _fub_client(connection_id, fub)
        body, st = client.get_by_uri(u)
        if st == 401 and _refresh():
            client = _fub_client(connection_id, fub)
            body, st = client.get_by_uri(u)
        rec = _coerce_fub_person_record(body)
        out["via"] = "uri"
        out["final_http"] = st
        if st < 400 and rec is not None:
            payload["fubPerson"] = rec
            out["fubPersonSet"] = True
            out["person_id"] = rec.get("id")
            _logger.warning(
                "fub_webhook_enrich ok via=uri connection_id=%s event=%s http=%s person_id=%s refreshed=%s",
                connection_id,
                ev,
                st,
                rec.get("id"),
                out["oauthRefreshed"],
            )
            return out
        _logger.warning(
            "fub_webhook_enrich uri_fetch_failed connection_id=%s event=%s http=%s oauth_refreshed=%s body_keys=%s",
            connection_id,
            ev,
            st,
            out.get("oauthRefreshed"),
            list(body.keys())[:12] if isinstance(body, dict) else None,
        )

    pid = person_id_from_fub_webhook_payload(payload)
    out["resolved_person_id"] = pid
    if isinstance(pid, int) and pid > 0:
        client = _fub_client(connection_id, fub)
        body2, st2 = client.get_person(pid)
        if st2 == 401 and _refresh():
            client = _fub_client(connection_id, fub)
            body2, st2 = client.get_person(pid)
        rec2 = _coerce_fub_person_record(body2)
        out["via"] = "person_id"
        out["final_http"] = st2
        if st2 < 400 and rec2 is not None:
            payload["fubPerson"] = rec2
            out["fubPersonSet"] = True
            out["person_id"] = rec2.get("id")
            _logger.warning(
                "fub_webhook_enrich ok via=person_id connection_id=%s event=%s person_id=%s http=%s refreshed=%s",
                connection_id,
                ev,
                pid,
                st2,
                out["oauthRefreshed"],
            )
            return out
        _logger.warning(
            "fub_webhook_enrich person_fetch_failed connection_id=%s event=%s person_id=%s http=%s oauth_refreshed=%s body_keys=%s",
            connection_id,
            ev,
            pid,
            st2,
            out.get("oauthRefreshed"),
            list(body2.keys())[:12] if isinstance(body2, dict) else None,
        )
        return out

    out["skipped"] = "no_person_ref"
    _logger.warning(
        "fub_webhook_enrich skipped_no_person_ref connection_id=%s event=%s keys=%s",
        connection_id,
        ev,
        list(payload.keys())[:12],
    )
    return out

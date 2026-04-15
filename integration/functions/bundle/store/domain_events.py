"""Best-effort domain events to acs-domain-events (never raises into request handlers)."""

from __future__ import annotations

import logging
from typing import Any

from store.events_publish import publish_domain_event

_logger = logging.getLogger(__name__)

SOURCE_FUB = "/integration/followupboss"


def _try_publish(event_type: str, data: dict, *, subject: str = "") -> None:
    try:
        body, status = publish_domain_event(
            event_type=event_type,
            data=data,
            source=SOURCE_FUB,
            subject=subject,
        )
        if status >= 400:
            _logger.warning("domain event %s failed: http=%s body=%s", event_type, status, body)
    except Exception:
        _logger.exception("domain event %s raised", event_type)


def summarize_webhook_state(w: dict[str, Any]) -> dict[str, Any]:
    """Small payload for Pub/Sub (avoid huge nested FUB errors)."""
    if not isinstance(w, dict):
        return {}
    keys = (
        "syncStatus",
        "deferred",
        "enqueuedAtEpoch",
        "created",
        "kept",
        "removed",
        "ok",
        "webhookSyncStatus",
        "listHttpStatus",
        "error",
        "usedRefresh",
        "usedApiKeyFallback",
        "totalEvents",
    )
    return {k: w[k] for k in keys if k in w}


def summarize_webhook_cleanup(c: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(c, dict):
        return {}
    keys = ("removed", "listHttpStatus", "error", "usedRefresh", "usedApiKeyFallback")
    return {k: c[k] for k in keys if k in c}


def emit_followupboss_oauth_connected(
    uid: str,
    *,
    connection_status: str,
    webhook_sync_deferred: bool,
    webhook_sync: dict[str, Any],
) -> None:
    _try_publish(
        "com.acs.integration.followupboss.oauth_connected",
        {
            "realtorUid": uid,
            "connectionStatus": connection_status,
            "webhookSyncDeferred": webhook_sync_deferred,
            "webhookSync": summarize_webhook_state(webhook_sync),
        },
        subject=uid,
    )


def emit_followupboss_webhooks_sync_completed(
    uid: str,
    *,
    connection_status: str,
    webhook_sync: dict[str, Any],
) -> None:
    _try_publish(
        "com.acs.integration.followupboss.webhooks_sync_completed",
        {
            "realtorUid": uid,
            "connectionStatus": connection_status,
            "webhookSync": summarize_webhook_state(webhook_sync),
        },
        subject=uid,
    )


def emit_followupboss_disconnected(
    uid: str,
    *,
    webhook_cleanup: dict[str, Any],
    event_ledger_deleted: int,
) -> None:
    _try_publish(
        "com.acs.integration.followupboss.disconnected",
        {
            "realtorUid": uid,
            "webhookCleanup": summarize_webhook_cleanup(webhook_cleanup),
            "eventLedgerDeleted": event_ledger_deleted,
        },
        subject=uid,
    )


def emit_followupboss_webhooks_resynced(uid: str, *, webhook_sync: dict[str, Any]) -> None:
    _try_publish(
        "com.acs.integration.followupboss.webhooks_resynced",
        {
            "realtorUid": uid,
            "webhookSync": summarize_webhook_state(webhook_sync),
        },
        subject=uid,
    )

"""Enqueue Follow Up Boss webhook registration to Cloud Tasks (OAuth callback fast path)."""

import base64
import json
import logging
import os

_logger = logging.getLogger(__name__)


def enqueue_fub_webhook_sync(uid: str) -> tuple[bool, str | None]:
    """
    POST a task that invokes internal_webhook_sync on integration-bridge.
    Requires FUB_WEBHOOK_SYNC_QUEUE, FUB_WEBHOOK_SYNC_WORKER_URL, BACKEND_SERVICE_ACCOUNT_EMAIL,
    and FUB_WEBHOOK_SYNC_OIDC_AUDIENCE (typically the Cloud Run / Functions URL root).
    """
    queue_path = (os.environ.get("FUB_WEBHOOK_SYNC_QUEUE") or "").strip()
    worker_base = (os.environ.get("FUB_WEBHOOK_SYNC_WORKER_URL") or "").strip().rstrip("/")
    sa_email = (os.environ.get("BACKEND_SERVICE_ACCOUNT_EMAIL") or "").strip()
    audience = (os.environ.get("FUB_WEBHOOK_SYNC_OIDC_AUDIENCE") or worker_base).strip().rstrip("/")
    if not queue_path or not worker_base or not sa_email:
        return False, "webhook sync task env not configured"
    try:
        from google.cloud import tasks_v2
    except ImportError as e:
        return False, str(e)

    client = tasks_v2.CloudTasksClient()
    url = f"{worker_base}/integrations/followupboss/internal/webhook_sync"
    body = json.dumps({"uid": uid}).encode("utf-8")
    task: dict = {
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": url,
            "headers": {"Content-Type": "application/json"},
            "body": base64.b64encode(body).decode("ascii"),
            "oidc_token": {
                "service_account_email": sa_email,
                "audience": audience,
            },
        }
    }
    try:
        client.create_task(request={"parent": queue_path, "task": task})
        return True, None
    except Exception as e:
        _logger.exception("enqueue_fub_webhook_sync failed")
        return False, str(e)

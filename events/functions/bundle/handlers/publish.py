"""POST /events/v1/publish — JSON envelope to Pub/Sub acs-domain-events."""

import json
import os
import re
import uuid
from datetime import datetime, timezone

from google.cloud import pubsub_v1

from platform_auth import optional_acting_uid, verify_platform_request

_TYPE_RE = re.compile(r"^[a-zA-Z0-9._-]{1,256}$")


def _json(body: dict, status: int):
    return (json.dumps(body), status, {"Content-Type": "application/json"})


def handle_publish(request):
    _, err = verify_platform_request(request)
    if err:
        return _json(err[0], err[1])

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _json({"error": "JSON object body required"}, 400)

    event_type = body.get("type")
    if not isinstance(event_type, str) or not event_type.strip():
        return _json({"error": "type is required (non-empty string)"}, 400)
    event_type = event_type.strip()
    if not _TYPE_RE.match(event_type):
        return _json({"error": "type has invalid format"}, 400)

    data = body.get("data")
    if isinstance(data, dict):
        pass
    elif data is None:
        return _json({"error": "data is required (object)"}, 400)
    else:
        return _json({"error": "data must be a JSON object"}, 400)

    source = body.get("source")
    if source is not None and not isinstance(source, str):
        return _json({"error": "source must be a string when set"}, 400)
    source = (source or "/acs/unknown").strip() or "/acs/unknown"

    subject = body.get("subject")
    if subject is not None and not isinstance(subject, str):
        return _json({"error": "subject must be a string when set"}, 400)
    subject = (subject or "").strip()

    topic_id = (os.environ.get("PUBSUB_TOPIC_ID") or "").strip()
    if not topic_id:
        return _json({"error": "PUBSUB_TOPIC_ID not configured"}, 503)

    event_id = str(uuid.uuid4())
    time_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    envelope = {
        "specversion": "1.0",
        "id": event_id,
        "source": source,
        "type": event_type,
        "time": time_iso,
        "datacontenttype": "application/json",
        "data": data,
    }
    if subject:
        envelope["subject"] = subject

    acting = optional_acting_uid(request)
    corr = (request.headers.get("X-ACS-Correlation-Id") or "").strip()

    payload = json.dumps(envelope, separators=(",", ":"), sort_keys=False).encode("utf-8")

    attrs = {
        "event_type": event_type[:1024],
        "source": source[:1024],
    }
    if subject:
        attrs["subject"] = subject[:1024]
    if acting:
        attrs["acting_uid"] = acting[:1024]
    if corr:
        attrs["correlation_id"] = corr[:1024]

    publisher = pubsub_v1.PublisherClient()
    future = publisher.publish(topic_id, payload, **attrs)
    message_id = future.result(timeout=30)

    return _json(
        {
            "ok": True,
            "messageId": message_id,
            "id": event_id,
        },
        200,
    )

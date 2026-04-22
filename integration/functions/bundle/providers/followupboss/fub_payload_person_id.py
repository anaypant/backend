"""Resolve FUB person id from webhook JSON (no HTTP / secrets)."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlparse

_URI_PERSON_RE = re.compile(r"/people/(\d+)\s*$", re.IGNORECASE)


def person_id_from_fub_webhook_payload(payload: dict[str, Any]) -> int | None:
    """Match core ``normalize_integration_payload`` person id rules (uri path, query, resourceIds)."""
    uri = payload.get("uri") if isinstance(payload.get("uri"), str) else None
    if isinstance(uri, str) and uri.strip():
        s = uri.strip()
        m = _URI_PERSON_RE.search(s)
        if m:
            try:
                v = int(m.group(1))
                return v if v > 0 else None
            except ValueError:
                pass
        try:
            parsed = urlparse(s)
            if "people" in (parsed.path or "").lower():
                for key in ("id", "personId", "person_id"):
                    vals = parse_qs(parsed.query).get(key)
                    if vals and str(vals[0]).strip().isdigit():
                        v = int(str(vals[0]).strip())
                        return v if v > 0 else None
        except (TypeError, ValueError):
            pass

    ri = payload.get("resourceIds")
    if isinstance(ri, list):
        for x in ri:
            if isinstance(x, int) and x > 0:
                return x
            if isinstance(x, str) and x.strip().isdigit():
                return int(x.strip())
    return None

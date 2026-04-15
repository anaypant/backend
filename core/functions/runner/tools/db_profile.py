"""Merge fields into Realtors/{uid} via DB internal API (allowlisted paths)."""

from __future__ import annotations

import re
from typing import Any

from clients import db_internal

_PATH_OK = re.compile(r"^Realtors/[a-zA-Z0-9_-]{1,128}$")


def merge_realtor_profile(uid: str, data: dict[str, Any]) -> tuple[dict, int]:
    if not isinstance(uid, str) or not uid.strip():
        return {"error": "uid required"}, 400
    if not isinstance(data, dict) or not data:
        return {"error": "data must be a non-empty object"}, 400
    path = f"Realtors/{uid.strip()}"
    if not _PATH_OK.match(path):
        return {"error": "path not allowlisted"}, 403
    return db_internal.upsert_merge(path, data, acting_uid=uid.strip())

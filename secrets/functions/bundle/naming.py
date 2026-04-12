"""Deterministic GSM secret ids and acs-sec://v1 refs for realtor-scoped keys."""

from __future__ import annotations

import base64
import binascii
import hashlib

PREFIX = "acs-sec-v1-realtor-"


def physical_secret_id(scope: str, scope_id: str, key: str) -> str:
    if scope != "realtor":
        raise ValueError(f"unsupported scope: {scope}")
    if not scope_id or not key:
        raise ValueError("scopeId and key are required")
    kd = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
    uenc = base64.urlsafe_b64encode(scope_id.encode("utf-8")).decode("ascii").rstrip("=")
    return f"{PREFIX}{kd}-{uenc}"


def ref_for_secret_id(secret_id: str) -> str:
    return f"acs-sec://v1/{secret_id}"


def parse_ref(ref: str) -> str | None:
    p = "acs-sec://v1/"
    if not ref.startswith(p):
        return None
    sid = ref[len(p) :].strip()
    return sid or None


def scope_id_from_secret_id(secret_id: str) -> str | None:
    if not secret_id.startswith(PREFIX):
        return None
    rest = secret_id[len(PREFIX) :]
    idx = rest.rfind("-")
    if idx <= 0:
        return None
    uenc = rest[idx + 1 :]
    kd = rest[:idx]
    if len(kd) != 24:
        return None
    if any(c not in "0123456789abcdef" for c in kd.lower()):
        return None
    pad = "=" * ((4 - len(uenc) % 4) % 4)
    try:
        raw = base64.urlsafe_b64decode(uenc + pad)
        return raw.decode("utf-8")
    except (ValueError, binascii.Error, UnicodeDecodeError):
        return None

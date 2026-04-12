"""Parse acs-sec://v1 refs (must stay in sync with secrets-bridge naming.PREFIX)."""

from __future__ import annotations

import base64
import binascii

PREFIX = "acs-sec-v1-realtor-"


def scope_id_from_acs_sec_ref(ref: str) -> str | None:
    """Return realtor Firebase uid encoded in the ref, or None."""
    p = "acs-sec://v1/"
    if not ref.startswith(p):
        return None
    secret_id = ref[len(p) :].strip()
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

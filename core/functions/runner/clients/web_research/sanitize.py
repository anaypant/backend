"""Strip control/special characters and non-ASCII for safer downstream LLM ingestion."""

from __future__ import annotations

import re

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WS = re.compile(r"\s+")


def strip_non_ascii(text: str) -> str:
    return text.encode("ascii", "ignore").decode("ascii")


def sanitize_page_text(text: str, *, max_chars: int = 48_000) -> str:
    if not isinstance(text, str):
        return ""
    t = _CTRL.sub(" ", text)
    t = strip_non_ascii(t)
    t = _WS.sub(" ", t).strip()
    if len(t) > max_chars:
        t = t[:max_chars]
    return t

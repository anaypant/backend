"""Echo provider for tests — returns fixed text without external calls."""

from __future__ import annotations

from typing import Any


def complete(
    *,
    model: str,
    messages: list[dict[str, Any]],
    response_format: str | None,
    provider_options: dict[str, Any] | None,
) -> tuple[dict[str, Any], int]:
    last = ""
    for m in reversed(messages):
        if isinstance(m, dict) and isinstance(m.get("content"), str):
            last = m["content"]
            break
    text = f"[echo:{model}] {last}" if last else f"[echo:{model}]"
    out: dict[str, Any] = {"provider": "echo", "text": text}
    if response_format == "json":
        out["json"] = {"echo": True, "text": text}
        del out["text"]
    return out, 200

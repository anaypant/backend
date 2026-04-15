"""Dispatch to provider by name."""

from __future__ import annotations

from typing import Any, Callable

from providers import echo, openrouter

ProviderFn = Callable[..., tuple[dict[str, Any], int]]

_REGISTRY: dict[str, ProviderFn] = {
    "openrouter": openrouter.complete,
    "echo": echo.complete,
}


def get_provider(name: str | None) -> ProviderFn | None:
    key = (name or "openrouter").strip().lower()
    return _REGISTRY.get(key)

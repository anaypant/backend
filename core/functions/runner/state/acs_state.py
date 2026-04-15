"""Helpers for ACSStateV1-shaped dicts."""

from __future__ import annotations

from typing import Any


def ensure_metadata(acs: dict) -> dict:
    meta = acs.get("metadata")
    if not isinstance(meta, dict):
        meta = {}
        acs["metadata"] = meta
    return meta


def append_error(acs: dict, message: str, *, phase: str = "workflow") -> None:
    errs = acs.get("errors")
    if not isinstance(errs, list):
        errs = []
    errs.append({"phase": phase, "message": message})
    acs["errors"] = errs


def set_core_meta(acs: dict, patch: dict[str, Any]) -> None:
    meta = ensure_metadata(acs)
    cur = meta.get("core")
    if not isinstance(cur, dict):
        cur = {}
    cur.update(patch)
    meta["core"] = cur

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


def merge_state_bridge_patch(acs: dict, patch: dict[str, Any]) -> None:
    """Merge ``acs_patch`` from integration ``from_providers`` into ``acs``."""
    if not isinstance(patch, dict) or not patch:
        return
    src = patch.get("source")
    if isinstance(src, dict):
        cur = acs.get("source")
        if isinstance(cur, dict):
            cur.update(src)
        else:
            acs["source"] = dict(src)
    pp = patch.get("payload")
    if not isinstance(pp, dict):
        return
    target = acs.setdefault("payload", {})
    if not isinstance(target, dict):
        target = {}
        acs["payload"] = target
    for k, v in pp.items():
        if k == "source_batches" and isinstance(v, list):
            existing = target.get("source_batches")
            if isinstance(existing, list):
                target["source_batches"] = existing + v
            else:
                target["source_batches"] = v
        elif k == "_integration" and isinstance(v, dict):
            cur_i = target.get("_integration")
            if isinstance(cur_i, dict):
                cur_i.update(v)
            else:
                target["_integration"] = dict(v)
        else:
            target[k] = v

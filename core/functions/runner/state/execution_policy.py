"""Execution policy (analytical vs hands-on) embedded in ACS state metadata."""

from __future__ import annotations

POLICY_VERSION = 1


def default_execution_policy() -> dict:
    """When ``metadata.execution_policy`` is missing — assume analytical (safe default)."""
    return {
        "policy_version": POLICY_VERSION,
        "volatile_external_allowed": False,
        "integration_maintenance_allowed": True,
        "guardrail_level": 0,
    }


def get_execution_policy(acs: dict) -> dict:
    meta = acs.get("metadata")
    if isinstance(meta, dict):
        p = meta.get("execution_policy")
        if isinstance(p, dict):
            return normalize_execution_policy(p)
    return default_execution_policy()


def normalize_execution_policy(p: dict) -> dict:
    out = default_execution_policy()
    out["policy_version"] = int(p.get("policy_version") or POLICY_VERSION)
    if "volatile_external_allowed" in p:
        out["volatile_external_allowed"] = bool(p.get("volatile_external_allowed"))
    if "integration_maintenance_allowed" in p:
        out["integration_maintenance_allowed"] = bool(p.get("integration_maintenance_allowed"))
    if "guardrail_level" in p:
        gl = p.get("guardrail_level")
        out["guardrail_level"] = 1 if gl == 1 else 0
    return out


def integration_maintenance_allowed(acs: dict) -> bool:
    return bool(get_execution_policy(acs).get("integration_maintenance_allowed", True))


def volatile_external_allowed(acs: dict) -> bool:
    return bool(get_execution_policy(acs).get("volatile_external_allowed"))

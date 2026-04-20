"""Build ``metadata.execution_policy`` from persisted realtor profile (guardrail level)."""

from __future__ import annotations

POLICY_VERSION = 1


def execution_policy_from_profile(profile: dict | None) -> dict:
    data = profile if isinstance(profile, dict) else {}
    hands_on = data.get("guardrailLevel") == 1
    return {
        "policy_version": POLICY_VERSION,
        "volatile_external_allowed": hands_on,
        "integration_maintenance_allowed": True,
        "guardrail_level": 1 if hands_on else 0,
    }

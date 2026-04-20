import os

from dispatcher.outbound_policy import action_is_volatile_external, partition_outbound_actions

__all__ = [
    "action_is_volatile_external",
    "dispatch_provider_actions",
    "extract_actions_from_state",
    "outbound_enabled",
    "partition_outbound_actions",
]


def dispatch_provider_actions(provider: str, connection_id: str, actions: list[dict]) -> dict:
    if provider == "followupboss":
        from providers.followupboss.egress import apply_outbound_actions as fub_apply

        return fub_apply(connection_id, actions)
    return {"ok": False, "error": f"unsupported provider: {provider}"}


def extract_actions_from_state(state: dict) -> list[dict]:
    """Provider-agnostic action envelope in metadata.outboundActions list."""
    meta = dict(state.get("metadata") or {})
    actions = meta.get("outboundActions")
    return actions if isinstance(actions, list) else []


def outbound_enabled() -> bool:
    return (os.environ.get("ACS_ENABLE_OUTBOUND_EGRESS") or "1").strip() not in ("0", "false", "False")

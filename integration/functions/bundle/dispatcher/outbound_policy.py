"""Outbound action partitioning (no provider client imports)."""


def action_is_volatile_external(action: dict) -> bool:
    """
    Outbound actions default to volatile (require ``volatile_external_allowed``).

    Set ``effect`` to ``internal`` only for actions that must never hit an external CRM (rare for FUB).
    """
    effect = action.get("effect")
    if effect == "internal":
        return False
    if effect == "volatile_external":
        return True
    return True


def partition_outbound_actions(
    actions: list[dict],
    policy: dict,
) -> tuple[list[dict], list[dict]]:
    """
    Split actions into those permitted to execute vs skipped for observability.

    ``policy`` uses the same shape as ``metadata.execution_policy`` (``volatile_external_allowed``).
    """
    volatile_ok = policy.get("volatile_external_allowed") is True
    to_apply: list[dict] = []
    skipped: list[dict] = []
    for raw in actions:
        if not isinstance(raw, dict):
            skipped.append({"action": raw, "reason": "invalid_action"})
            continue
        if action_is_volatile_external(raw) and not volatile_ok:
            skipped.append({"action": raw, "reason": "volatile_external_blocked_by_policy"})
            continue
        to_apply.append(raw)
    return to_apply, skipped

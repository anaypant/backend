"""Invoke core-run with ACS state.

Integration calls core **only** from Follow Up Boss webhook ingress (and realtor ``webhook_test``),
where normalized external events become ``ACSStateV1`` and run a workflow. Provider OAuth, CRM
read APIs (e.g. ``people/list``), and refresh stay in integration without invoking core; clients
call ``/core/v1/run`` via the gateway when they need a workflow.
"""

from typing import Any

from store.common import core_origin, post_json


def send_state_to_core(
    state: dict,
    workflow_id: str | None = None,
    *,
    timeout: int = 20,
) -> tuple[dict, int]:
    payload: dict[str, Any] = {"state": state}
    if workflow_id:
        payload["workflow_id"] = workflow_id
    return post_json(core_origin() + "/core/v1/run/", payload, timeout=timeout)

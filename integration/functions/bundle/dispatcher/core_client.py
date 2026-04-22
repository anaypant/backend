"""Invoke core-run with ACS state.

Integration calls core from Follow Up Boss webhook ingress (and realtor ``webhook_test``) after
any CRM-side enrichment (e.g. ``fubPerson`` via ``GET`` webhook ``uri``) so core does not need
integration credentials for that path. Provider OAuth, list APIs, and refresh stay in integration;
clients call ``/core/v1/run`` via the gateway when they need a workflow.
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

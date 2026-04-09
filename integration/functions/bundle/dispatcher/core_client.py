from typing import Any

from store.common import core_origin, post_json


def send_state_to_core(state: dict, workflow_id: str | None = None) -> tuple[dict, int]:
    payload: dict[str, Any] = {"state": state}
    if workflow_id:
        payload["workflow_id"] = workflow_id
    return post_json(core_origin() + "/core/v1/run/", payload, timeout=20)

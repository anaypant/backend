"""Invoke core-run with ACS state.

**Ownership:** Integration performs CRM auth, webhook verification, optional person hydration,
canonical ``IntegrationWebhookEventV1`` → ``ACSStateV1`` (``schema/canonical_webhook``), resolves
one or more ``workflow_id`` values, then POSTs here **once per workflow** with a deep-copied
``state``. Core never holds FUB OAuth secrets for the webhook read path.

Provider OAuth, list APIs, and refresh remain in integration; browser or internal clients may
also call ``/core/v1/run`` via the public gateway when running workflows directly.

Some FUB migration entrypoints (e.g. ``/integrations/followupboss/import`` and
``/integrations/followupboss/migration/import-batch``) materialize CRM rows in integration before
calling core, so core-run does not need ``INTEGRATION_BRIDGE_BASE_URL`` for those paths.
"""

from typing import Any

from store.common import core_origin, post_json
from store.gcp_identity import id_token_for_core_gateway


def send_state_to_core(
    state: dict,
    workflow_id: str | None = None,
    *,
    timeout: int = 20,
) -> tuple[dict, int]:
    payload: dict[str, Any] = {"state": state}
    if workflow_id:
        payload["workflow_id"] = workflow_id
    token = id_token_for_core_gateway()
    return post_json(
        core_origin() + "/core/v1/run/",
        payload,
        headers={"Authorization": f"Bearer {token}"},
        timeout=timeout,
    )

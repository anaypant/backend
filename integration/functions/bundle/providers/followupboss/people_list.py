"""Read-only Follow Up Boss people page — integration I/O only (no core workflows)."""

from __future__ import annotations

from typing import Any

from providers.followupboss import fub_people_ops
from store.authn import resolve_realtor_bearer
from store.common import integration_auth_error_response, json_response


def list_people_page(request):
    """
    POST /integrations/followupboss/people/list

    Returns one page from FUB ``GET /v1/people``. Core workflows load the same page via
    ``POST …/internal/state/from_providers`` (platform OIDC) with ``people_list_request``.
    """
    decoded, err, _token = resolve_realtor_bearer(request)
    if err:
        return integration_auth_error_response(err)
    uid = decoded["uid"]

    if request.method != "POST":
        return json_response({"error": "method not allowed"}, 405)

    try:
        body_in = request.get_json(silent=True) or {}
    except Exception:
        body_in = {}
    if not isinstance(body_in, dict):
        body_in = {}

    bs, off, nxt = fub_people_ops.parse_list_request(body_in)
    data, err_st = fub_people_ops.fetch_people_page(uid, batch_size=bs, offset=off, next_token=nxt)
    if err_st is not None:
        if err_st == 400:
            return json_response(data, 400)
        if err_st == 404:
            return json_response(data, 404)
        return json_response(data, 502)

    out: dict[str, Any] = {
        "provider": "followupboss",
        "people": data.get("people") if isinstance(data.get("people"), list) else [],
        "_metadata": data.get("_metadata") if isinstance(data.get("_metadata"), dict) else {},
    }
    return json_response(out, 200)

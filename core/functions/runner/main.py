# Core microservice: LangGraph workflows will plug in here. See backend/contracts/.

import acs_internal as acs

import json
import uuid

import functions_framework


def _json_response(payload: dict, status: int):
    return (json.dumps(payload), status, {"Content-Type": "application/json"})


@functions_framework.http
def main(request):
    """
    POST /core/v1/run (via internal API Gateway).

    Body (CoreRunRequestV1): { "workflow_id"?: str, "state": ACSStateV1 }
    Response: { "status", "state", "error"?: str }
    """
    if request.method != "POST":
        return _json_response({"error": "method not allowed"}, 405)

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _json_response({"error": "JSON object body required"}, 400)

    state = body.get("state")
    if not isinstance(state, dict):
        return _json_response({"error": "state must be an object"}, 400)

    workflow_id = body.get("workflow_id")
    if workflow_id is not None and not isinstance(workflow_id, str):
        return _json_response({"error": "workflow_id must be a string when provided"}, 400)

    # Optional: propagate user for future rate limits (header may be absent for internal jobs).
    _user_hdr = request.headers.get(acs.USER_JWT_HEADER) or ""

    correlation = state.get("correlation_id") or str(uuid.uuid4())
    out_state = dict(state)
    out_state.setdefault("correlation_id", correlation)
    meta = dict(out_state.get("metadata") or {})
    meta["core"] = {
        "handler": "stub",
        "workflow_id": workflow_id,
        # TODO: attach uid from verified JWT when workflows enforce per-user limits.
        "received_user_header": bool(_user_hdr),
    }
    out_state["metadata"] = meta

    return _json_response(
        {
            "status": "completed",
            "state": out_state,
            "error": None,
        },
        200,
    )

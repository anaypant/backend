# Core microservice: LangGraph workflows. See backend/contracts/.

from __future__ import annotations

import json
import traceback
import uuid

import functions_framework

import acs_internal as acs

from workflows import registry as wf_registry


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

    _user_hdr = request.headers.get(acs.USER_JWT_HEADER) or request.headers.get(
        acs.USER_AUTHORIZATION_HEADER
    ) or ""

    correlation = state.get("correlation_id") or str(uuid.uuid4())
    out_state = dict(state)
    out_state.setdefault("correlation_id", correlation)
    meta = dict(out_state.get("metadata") or {})
    meta.setdefault("core", {})

    if workflow_id and wf_registry.is_registered(workflow_id):
        try:
            out_state = wf_registry.run_workflow(workflow_id, out_state)
            meta = dict(out_state.get("metadata") or {})
            core_meta = meta.get("core") if isinstance(meta.get("core"), dict) else {}
            wf_status = core_meta.get("status")
            http = 200
            top = "completed"
            if wf_status == "failed":
                http = 500
                top = "failed"
            out_state["metadata"] = meta
            return _json_response(
                {
                    "status": top,
                    "state": out_state,
                    "error": None if wf_status != "failed" else "workflow reported failure",
                },
                http,
            )
        except Exception:
            err = traceback.format_exc()
            meta["core"] = dict(meta.get("core") or {})
            meta["core"]["handler"] = "workflow_error"
            meta["core"]["detail"] = err[-8000:]
            out_state["metadata"] = meta
            acs_errors = out_state.get("errors")
            if not isinstance(acs_errors, list):
                acs_errors = []
            acs_errors.append({"phase": "workflow", "message": "unhandled exception in workflow engine"})
            out_state["errors"] = acs_errors
            return _json_response(
                {
                    "status": "error",
                    "state": out_state,
                    "error": "workflow execution failed",
                },
                500,
            )

    meta["core"] = {
        "handler": "stub",
        "workflow_id": workflow_id,
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

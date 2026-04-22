# Core microservice: LangGraph workflows. See backend/contracts/.

from __future__ import annotations

import json
import logging
import traceback
import uuid

import functions_framework

import acs_internal as acs

from dev_lab_http import try_dev_lab_response
from workflows import registry as wf_registry

_logger = logging.getLogger(__name__)

# Default root level is WARNING; workflow modules log at INFO and would be dropped.
logging.getLogger().setLevel(logging.INFO)


def _log_workflow_outcome(exec_workflow_id: str, out_state: dict) -> None:
    """One stderr line for Logs Explorer: phase, graph path, outbound count, common skip reasons."""
    meta = out_state.get("metadata") if isinstance(out_state.get("metadata"), dict) else {}
    core = meta.get("core") if isinstance(meta.get("core"), dict) else {}
    phase = core.get("phase")
    wa = meta.get("workflowAudit") if isinstance(meta.get("workflowAudit"), dict) else {}
    nodes = wa.get("nodes") if isinstance(wa.get("nodes"), list) else []
    trail = "->".join(
        str(n.get("node")) for n in nodes if isinstance(n, dict) and isinstance(n.get("node"), str)
    )
    if len(trail) > 600:
        trail = trail[:600] + "...[truncated]"

    oa = meta.get("outboundActions")
    oa_n = len(oa) if isinstance(oa, list) else 0

    ce = meta.get("contactEnrichment") if isinstance(meta.get("contactEnrichment"), dict) else {}
    hints: list[str] = []
    ie = meta.get("integrationEnrich") if isinstance(meta.get("integrationEnrich"), dict) else {}
    if ie:
        if ie.get("fubPersonSet") is True:
            hints.append("fub_person_enriched")
        sk = ie.get("skipped")
        if isinstance(sk, str) and sk.strip():
            hints.append(f"int_enrich_skip={sk}")
        fh = ie.get("final_http")
        if fh is not None:
            hints.append(f"int_enrich_http={fh}")
        if ie.get("oauthRefreshed") is True:
            hints.append("int_oauth_refreshed")

    if ce.get("internalClientExists") is True:
        hints.append("duplicate_internal_client")
    syn = ce.get("synthesis") if isinstance(ce.get("synthesis"), dict) else {}
    if syn.get("fallback_note") is True:
        hints.append("synthesis_fallback_note")
    egress = ce.get("egress")
    if isinstance(egress, dict):
        mode = egress.get("mode")
        http = egress.get("http_status")
        if mode:
            hints.append(f"egress_mode={mode}")
        elif http is not None:
            hints.append(f"egress_http={http}")

    err_list = out_state.get("errors")
    err_n = len(err_list) if isinstance(err_list, list) else 0

    wr = meta.get("workflow_routing") if isinstance(meta.get("workflow_routing"), dict) else {}
    routing = ""
    if isinstance(wr.get("substituted_workflow_id"), str) and wr["substituted_workflow_id"].strip():
        routing = f" substituted={wr.get('substituted_workflow_id')}"

    _logger.info(
        "workflow outcome exec_workflow_id=%s correlation_id=%s phase=%s node_trail=%s outbound_actions=%s error_count=%s hints=%s%s",
        exec_workflow_id,
        out_state.get("correlation_id"),
        phase,
        trail or "(none)",
        oa_n,
        err_n,
        ",".join(hints) if hints else "-",
        routing,
    )


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

    dev_out = try_dev_lab_response(body)
    if dev_out is not None:
        dev_payload, dev_status = dev_out
        return _json_response(dev_payload, dev_status)

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
            exec_workflow_id = wf_registry.resolve_registered_workflow_id(workflow_id, out_state)
            _logger.info(
                "workflow start workflow_id=%s exec_workflow_id=%s correlation_id=%s user_id=%s",
                workflow_id,
                exec_workflow_id,
                out_state.get("correlation_id"),
                out_state.get("user_id"),
            )
            out_state = wf_registry.run_workflow(exec_workflow_id, out_state)
            meta = dict(out_state.get("metadata") or {})
            core_meta = meta.get("core") if isinstance(meta.get("core"), dict) else {}
            wf_status = core_meta.get("status")
            http = 200
            top = "completed"
            if wf_status == "failed":
                http = 500
                top = "failed"
            _log_workflow_outcome(exec_workflow_id, out_state)
            _logger.info(
                "workflow end workflow_id=%s correlation_id=%s top_status=%s wf_status=%s",
                workflow_id,
                out_state.get("correlation_id"),
                top,
                wf_status,
            )
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
            _logger.exception(
                "workflow raised workflow_id=%s correlation_id=%s",
                workflow_id,
                out_state.get("correlation_id"),
            )
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

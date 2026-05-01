# Core microservice: LangGraph workflows. See backend/contracts/.

from __future__ import annotations

import datetime
import json
import logging
import traceback
import uuid

import functions_framework

import acs_internal as acs

from clients import db_internal
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


def _persist_workflow_audit(exec_workflow_id: str, top: str, out_state: dict) -> None:
    """Best-effort write of workflowAudit to Realtors/{uid}/WorkflowActivity/{correlation_id}."""
    uid = out_state.get("user_id")
    if not isinstance(uid, str) or not uid.strip():
        return
    correlation = out_state.get("correlation_id")
    if not isinstance(correlation, str) or not correlation.strip():
        correlation = str(uuid.uuid4())

    meta = out_state.get("metadata") if isinstance(out_state.get("metadata"), dict) else {}
    wa = meta.get("workflowAudit") if isinstance(meta.get("workflowAudit"), dict) else {}

    doc_path = f"Realtors/{uid.strip()}/WorkflowActivity/{correlation.strip()}"
    doc_data: dict = {
        "ownerUid": uid.strip(),
        "workflowId": exec_workflow_id,
        "status": top,
        "createdAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "metadata": {
            "workflowAudit": wa,
            "core": meta.get("core") if isinstance(meta.get("core"), dict) else {},
        },
    }
    try:
        _, http = db_internal.upsert_merge(doc_path, doc_data, acting_uid=uid.strip(), timeout=10)
        if http not in (200, 201):
            _logger.warning("workflow_audit_persist: db upsert returned %s for %s", http, doc_path)
    except Exception:
        _logger.warning("workflow_audit_persist: failed to write audit for %s", doc_path, exc_info=True)


# ---------------------------------------------------------------------------
# Glyde Lab handlers
# ---------------------------------------------------------------------------
# These endpoints live at /core/v1/lab/* and are registered in the API Gateway
# with path_translation = APPEND_PATH_TO_ADDRESS, so request.path contains the
# full path (e.g. "/core/v1/lab/graphs").  The existing /core/v1/run endpoint
# uses CONSTANT_ADDRESS so its requests arrive at path "/" — that path is
# handled by the standard workflow block below, unchanged.
# ---------------------------------------------------------------------------


def _handle_usage_request(request, path: str):
    """GET /core/v1/usage  — current-month usage summary for the authenticated user."""
    if request.method != "GET":
        return _json_response({"error": "method not allowed"}, 405)

    # Authenticate: accept either platform actor or end-user Firebase token
    import platform_auth as _plat
    import acs_internal as _acs
    from firebase_admin import auth as _fauth
    import firebase_admin as _fb

    uid: str | None = None
    # Try platform actor first (internal service-to-service call)
    decoded, plat_err = _plat.try_platform_actor(request)
    if plat_err is None and decoded is not None:
        uid = str(decoded.get("uid") or decoded.get("user_id") or "")

    # Fall back to end-user Firebase token
    if not uid:
        for hdr in (_acs.USER_JWT_HEADER, _acs.USER_AUTHORIZATION_HEADER):
            token = _acs.parse_bearer_header(request, hdr)
            if not token:
                continue
            try:
                if not _fb._apps:
                    _fb.initialize_app()
                claims = _fauth.verify_id_token(token, check_revoked=True)
                uid = str(claims.get("user_id") or claims.get("sub") or "")
                if uid:
                    break
            except Exception:
                pass

    if not uid:
        return _json_response({"error": "unauthorized"}, 401)

    try:
        from clients import usage_tracker as _ut
        summary = _ut.usage_summary(uid)
        return _json_response(summary, 200)
    except Exception:
        _logger.exception("usage endpoint error uid=%s", uid)
        return _json_response({"error": "failed to load usage"}, 500)


def _handle_lab_request(request, path: str):
    """Route and serve all /core/v1/lab/* requests."""
    # Import locally to avoid loading lab modules during cold-start of prod runs.
    import lab_graph as _lab_graph
    import lab_stream as _lab_stream
    from flask import Response, stream_with_context

    # ------------------------------------------------------------------
    # GET /core/v1/lab/graphs  →  list all workflow topologies
    # ------------------------------------------------------------------
    if path == "/core/v1/lab/graphs" and request.method == "GET":
        try:
            topologies = _lab_graph.list_topologies()
            return _json_response({"graphs": topologies}, 200)
        except Exception:
            _logger.exception("lab: list_topologies failed")
            return _json_response({"error": "topology extraction failed"}, 500)

    # ------------------------------------------------------------------
    # GET /core/v1/lab/graph/{workflow_id}  →  single workflow topology
    # ------------------------------------------------------------------
    prefix = "/core/v1/lab/graph/"
    if path.startswith(prefix) and request.method == "GET":
        wid = path[len(prefix):]
        if not wid:
            return _json_response({"error": "workflow_id required"}, 400)
        try:
            topo = _lab_graph.get_graph_topology(wid)
            return _json_response(topo, 200)
        except KeyError:
            return _json_response({"error": f"unknown workflow_id: {wid}"}, 404)
        except Exception:
            _logger.exception("lab: get_graph_topology failed wid=%s", wid)
            return _json_response({"error": "topology extraction failed"}, 500)

    # ------------------------------------------------------------------
    # POST /core/v1/lab/run  →  SSE streaming workflow execution
    # ------------------------------------------------------------------
    if path == "/core/v1/lab/run" and request.method == "POST":
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return _json_response({"error": "JSON object body required"}, 400)

        workflow_id = body.get("workflow_id")
        if not isinstance(workflow_id, str) or not workflow_id.strip():
            return _json_response({"error": "workflow_id string required"}, 400)

        state = body.get("state")
        if not isinstance(state, dict):
            return _json_response({"error": "state object required"}, 400)

        correlation_id: str | None = body.get("correlation_id") or state.get("correlation_id")

        _logger.info(
            "lab run_start workflow_id=%s correlation_id=%s user_id=%s",
            workflow_id,
            correlation_id or "(none)",
            state.get("user_id"),
        )

        gen = _lab_stream.stream_workflow_run(
            workflow_id.strip(),
            state,
            correlation_id=correlation_id,
        )
        return Response(
            stream_with_context(gen),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    return _json_response({"error": "lab endpoint not found", "path": path}, 404)


# ---------------------------------------------------------------------------
# Main HTTP handler
# ---------------------------------------------------------------------------


@functions_framework.http
def main(request):
    """
    POST /core/v1/run (via internal API Gateway).

    **Contract (production):** Body is ``CoreRunRequestV1``:
    ``{ "workflow_id"?: str, "state": ACSStateV1 }`` where ``ACSStateV1`` matches
    ``backend/contracts/acs_state.v1.json``. Integration is responsible for CRM auth,
    webhook ingress, ``IntegrationWebhookEventV1`` → ``ACSStateV1`` conversion
    (``schema/canonical_webhook`` + ``to_acs_state_v1``), webhook→workflow routing,
    and optional multi-workflow fan-out (each run gets its own POST here). Core runs
    LangGraph workflows and returns enriched ``state`` plus top-level ``status`` /
    ``error``.

    **Dev-only:** Top-level ``__ACS_DEV_LAB__`` markers (never inside ``state``) are
    handled by ``dev_lab_http`` when ``ACS_ENABLE_DEV_LAB=1`` (catalog, run_tool,
    run_unit_checks).

    **Lab endpoints:** GET/POST /core/v1/lab/* are served by ``_handle_lab_request``
    and registered in the API Gateway with ``path_translation = APPEND_PATH_TO_ADDRESS``
    so the path is preserved in ``request.path``.

    Response: ``{ "status", "state", "error"?: str }``.
    """
    # Lab endpoints arrive with their full path preserved (APPEND_PATH_TO_ADDRESS).
    path = (request.path or "/").rstrip("/") or "/"
    if path.startswith("/core/v1/lab"):
        return _handle_lab_request(request, path)

    if path.startswith("/core/v1/usage"):
        return _handle_usage_request(request, path)

    # All remaining paths use the existing POST-only workflow handler.
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
            _persist_workflow_audit(exec_workflow_id, top, out_state)
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

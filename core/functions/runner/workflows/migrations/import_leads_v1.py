"""migration.import_leads_v1 — provider batches → internal lead → Firestore ``Realtors/{uid}/Leads/*``."""

from __future__ import annotations

import logging
import time
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from clients import db_internal, integration_bridge
from state import acs_state
from workflows.migrations import provider_registry
from workflows.migrations.schemas import lead_internal_v1 as lead_schema

_logger = logging.getLogger(__name__)

_WORKFLOW_ID = "migration.import_leads_v1"


class ImportLeadsState(TypedDict, total=False):
    acs: dict[str, Any]
    failed: bool
    raw_batches: list[tuple[str, list[dict[str, Any]]]]
    internal_leads: list[dict[str, Any]]
    persist_errors: list[dict[str, Any]]


def _uid(acs: dict) -> str | None:
    u = acs.get("user_id")
    return u.strip() if isinstance(u, str) and u.strip() else None


def _ensure_provider_load_from_legacy_pagination(acs: dict) -> None:
    """If ``providerLoad`` is absent, derive it from ``fubPagination`` / ``fub_pagination``."""
    pay_raw = acs.get("payload")
    if not isinstance(pay_raw, dict):
        return
    pay = pay_raw
    pload = pay.get("providerLoad")
    if isinstance(pload, list) and pload:
        return
    fub = pay.get("fubPagination") or pay.get("fub_pagination")
    if not isinstance(fub, dict):
        return
    pay2 = acs.setdefault("payload", {})
    pay2["providerLoad"] = [
        {"provider": "followupboss", "kind": "people_list_request", "payload": dict(fub)},
    ]


def _parse_source_batches(acs: dict) -> list[tuple[str, list[dict[str, Any]]]]:
    payload = acs.get("payload") if isinstance(acs.get("payload"), dict) else {}
    batches = payload.get("source_batches")
    out: list[tuple[str, list[dict[str, Any]]]] = []
    if isinstance(batches, list):
        for b in batches:
            if not isinstance(b, dict):
                continue
            prov = b.get("provider")
            recs = b.get("records")
            if not isinstance(prov, str) or not prov.strip():
                continue
            if not isinstance(recs, list):
                continue
            rows = [r for r in recs if isinstance(r, dict)]
            if rows:
                out.append((prov.strip().lower(), rows))
        if out:
            return out

    # Legacy: payload.people + source.provider on ACS envelope
    people = payload.get("people")
    src = acs.get("source") if isinstance(acs.get("source"), dict) else {}
    prov = src.get("provider") if isinstance(src.get("provider"), str) else payload.get("provider")
    if isinstance(people, list) and isinstance(prov, str) and prov.strip():
        rows = [r for r in people if isinstance(r, dict)]
        if rows:
            out.append((prov.strip().lower(), rows))
    return out


def _node_integration_load(state: ImportLeadsState) -> dict[str, Any]:
    """Call integration ``from_providers`` when ``payload.providerLoad`` is set."""
    acs: dict = state["acs"]
    if state.get("failed"):
        return {"acs": acs}

    uid = _uid(acs)
    if not uid:
        acs_state.append_error(acs, "user_id required for migration.import_leads_v1")
        acs_state.set_core_meta(acs, {"workflow_id": _WORKFLOW_ID, "status": "failed", "phase": "integration_load"})
        return {"acs": acs, "failed": True}

    _ensure_provider_load_from_legacy_pagination(acs)
    pay = acs.get("payload") if isinstance(acs.get("payload"), dict) else {}
    pload = pay.get("providerLoad")
    if not isinstance(pload, list) or not pload:
        return {"acs": acs, "failed": False}

    blocks = [b for b in pload if isinstance(b, dict)]
    if not blocks:
        return {"acs": acs, "failed": False}

    resp, st = integration_bridge.from_providers(uid, blocks)
    if st >= 400:
        acs_state.append_error(
            acs,
            f"integration from_providers failed http={st} detail={resp.get('error') or resp.get('detail')}",
            phase="integration_load",
        )
        acs_state.set_core_meta(acs, {"workflow_id": _WORKFLOW_ID, "status": "failed", "phase": "integration_load"})
        return {"acs": acs, "failed": True}

    patch = resp.get("acs_patch")
    if not isinstance(patch, dict):
        acs_state.append_error(acs, "from_providers returned no acs_patch", phase="integration_load")
        acs_state.set_core_meta(acs, {"workflow_id": _WORKFLOW_ID, "status": "failed", "phase": "integration_load"})
        return {"acs": acs, "failed": True}

    acs_state.merge_state_bridge_patch(acs, patch)
    pay2 = acs.setdefault("payload", {})
    pay2["providerLoad"] = []

    meta = acs_state.ensure_metadata(acs)
    ic = meta.setdefault("integrationContext", {})
    if isinstance(ic, dict):
        ic["fromProvidersApplied"] = True

    return {"acs": acs, "failed": False}


def _node_integration_unload(state: ImportLeadsState) -> dict[str, Any]:
    """Call integration ``to_providers`` for summaries / outbound echoes (best-effort)."""
    acs: dict = state["acs"]
    uid = _uid(acs)
    if not uid:
        return {"acs": acs}

    body, st = integration_bridge.to_providers(uid, acs)
    meta = acs_state.ensure_metadata(acs)
    ic = meta.setdefault("integrationContext", {})
    if isinstance(ic, dict):
        ic["providerUnload"] = body.get("provider_states") if isinstance(body, dict) else []
        ic["toProvidersHttpStatus"] = st
        if isinstance(body, dict) and body.get("skipped"):
            ic["toProvidersSkipped"] = True
    return {"acs": acs}


def _node_ingress(state: ImportLeadsState) -> dict[str, Any]:
    acs: dict = state["acs"]
    uid = _uid(acs)
    if not uid:
        acs_state.append_error(acs, "user_id required for migration.import_leads_v1")
        acs_state.set_core_meta(acs, {"workflow_id": _WORKFLOW_ID, "status": "failed", "phase": "ingress"})
        return {"acs": acs, "failed": True}

    raw_batches = _parse_source_batches(acs)
    if not raw_batches:
        acs_state.append_error(acs, "payload.source_batches or payload.people + source.provider required")
        acs_state.set_core_meta(acs, {"workflow_id": _WORKFLOW_ID, "status": "failed", "phase": "ingress"})
        return {"acs": acs, "failed": True}

    meta = acs_state.ensure_metadata(acs)
    meta.setdefault("migrationImport", {})
    if isinstance(meta["migrationImport"], dict):
        meta["migrationImport"]["batchCount"] = len(raw_batches)

    _logger.info(
        "migration.import_leads_v1 ingress correlation_id=%s user_id=%s batches=%s",
        acs.get("correlation_id"),
        uid,
        len(raw_batches),
    )
    return {"acs": acs, "failed": False, "raw_batches": raw_batches}


def _node_normalize_internal(state: ImportLeadsState) -> dict[str, Any]:
    acs: dict = state["acs"]
    if state.get("failed"):
        return {"acs": acs}

    internal_leads: list[dict[str, Any]] = []
    for provider, rows in state.get("raw_batches") or []:
        for raw in rows:
            mapped = provider_registry.raw_record_to_internal(provider, raw)
            if mapped:
                internal_leads.append(mapped)

    meta = acs_state.ensure_metadata(acs)
    mig = meta.setdefault("migrationImport", {})
    if isinstance(mig, dict):
        mig["normalizedCount"] = len(internal_leads)

    if not internal_leads:
        acs_state.append_error(acs, "no records could be normalized (unknown provider or invalid rows)")
        acs_state.set_core_meta(acs, {"workflow_id": _WORKFLOW_ID, "status": "failed", "phase": "normalize"})
        return {"acs": acs, "failed": True, "internal_leads": []}

    return {"acs": acs, "internal_leads": internal_leads}


def _node_persist_leads(state: ImportLeadsState) -> dict[str, Any]:
    acs: dict = state["acs"]
    if state.get("failed"):
        return {"acs": acs}

    uid = _uid(acs)
    if not uid:
        return {"acs": acs, "failed": True}

    now = int(time.time())
    persisted = 0
    errors: list[dict[str, Any]] = []

    for lead in state.get("internal_leads") or []:
        if not isinstance(lead, dict):
            continue
        lid = lead.get("canonicalLeadId")
        if not isinstance(lid, str) or not lid.strip():
            errors.append({"reason": "missing_canonicalLeadId"})
            continue
        path = f"Realtors/{uid}/Leads/{lid.strip()}"
        data: dict[str, Any] = {
            "ownerUid": uid,
            "createdBy": uid,
            "lead": lead,
            "sourceProvider": lead.get("sourceProvider"),
            "externalLeadId": lead.get("externalId"),
            "leadSchemaVersion": lead_schema.LEAD_INTERNAL_SCHEMA_VERSION,
            "importedAtEpoch": now,
        }
        _body, st = db_internal.upsert_merge(path, data, acting_uid=uid)
        if st >= 400:
            errors.append({"canonicalLeadId": lid, "httpStatus": st})
        else:
            persisted += 1

    meta = acs_state.ensure_metadata(acs)
    mig = meta.setdefault("migrationImport", {})
    if isinstance(mig, dict):
        mig["persistedCount"] = persisted
        mig["persistFailedCount"] = len(errors)
        mig["persistErrors"] = errors[:25]

    if persisted == 0 and (state.get("internal_leads") or []):
        acs_state.append_error(acs, "all lead upserts failed")
        acs_state.set_core_meta(acs, {"workflow_id": _WORKFLOW_ID, "status": "failed", "phase": "persist"})
        return {"acs": acs, "failed": True, "persist_errors": errors}

    return {"acs": acs, "persist_errors": errors}


def _node_finalize(state: ImportLeadsState) -> dict[str, Any]:
    acs: dict = state["acs"]
    if state.get("failed"):
        acs_state.set_core_meta(acs, {"workflow_id": _WORKFLOW_ID, "status": "failed", "phase": "done"})
        return {"acs": acs}

    acs_state.set_core_meta(
        acs,
        {
            "workflow_id": _WORKFLOW_ID,
            "status": "completed",
            "phase": "done",
        },
    )
    return {"acs": acs}


def build_import_leads_graph():
    g = StateGraph(ImportLeadsState)
    g.add_node("integration_load", _node_integration_load)
    g.add_node("ingress", _node_ingress)
    g.add_node("normalize_internal", _node_normalize_internal)
    g.add_node("persist_leads", _node_persist_leads)
    g.add_node("integration_unload", _node_integration_unload)
    g.add_node("finalize", _node_finalize)
    g.set_entry_point("integration_load")
    g.add_edge("integration_load", "ingress")
    g.add_edge("ingress", "normalize_internal")
    g.add_edge("normalize_internal", "persist_leads")
    g.add_edge("persist_leads", "integration_unload")
    g.add_edge("integration_unload", "finalize")
    g.add_edge("finalize", END)
    return g.compile()

#!/usr/bin/env python3
"""
End-to-end lead intelligence test against a deployed ACS gateway.

Uses ~/.acs-cli/session.json (same as ``python -m cli.acs``): refreshes Firebase token if needed,
mutates Follow Up Boss (create person, tags, name change), waits for webhooks, reads Firestore
intel + score docs, calls webhook_test for a synchronous workflow_debug capture, restores
guardrailLevel when possible.

Run from repo ``backend/`` directory::

    python scripts/e2e_lead_intel_deployed.py

Artifacts: ``backend/e2e_runs/<run_id>/`` (JSON per step + SUMMARY.md).
"""

from __future__ import annotations

import base64
import json
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests

# ``backend/`` is the parent of ``scripts/``
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from cli.config import NotLoggedIn, _refresh, get_session  # noqa: E402
from cli.lead_intel_helpers import (  # noqa: E402
    canonical_lead_doc_id,
    fub_webhook_minimal_body,
    internal_client_doc_id,
    normalize_fub_webhook_event,
)


def _uid_from_token(tok: str) -> str:
    parts = tok.split(".")
    padded = parts[1] + "=" * (4 - len(parts[1]) % 4)
    payload = json.loads(base64.b64decode(padded.replace("-", "+").replace("_", "/")))
    uid = payload.get("user_id") or payload.get("sub")
    if not isinstance(uid, str) or not uid.strip():
        raise RuntimeError("Could not read uid from id_token")
    return uid.strip()


def _ensure_fresh_token(session: dict) -> dict:
    expires_at = int(session.get("expires_at") or 0)
    if time.time() >= expires_at - 60:
        return _refresh(session)
    return session


def _headers(tok: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {tok}",
        "X-ACS-Application-Authorization": f"Bearer {tok}",
    }


def _req(
    session: dict,
    method: str,
    path: str,
    *,
    json_body: dict | None = None,
    timeout: int = 120,
) -> tuple[int, object]:
    base = str(session.get("base_url") or "").rstrip("/")
    url = f"{base}/{path.lstrip('/')}"
    tok = session["id_token"]
    r = requests.request(
        method.upper(),
        url,
        json=json_body,
        headers=_headers(tok),
        timeout=timeout,
    )
    try:
        body = r.json()
    except Exception:
        body = r.text
    return r.status_code, body


def _save(out_dir: Path, name: str, obj: object) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"{name}.json"
    with p.open("w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, default=str)


def _person_id_from_create(resp: object) -> int | None:
    if not isinstance(resp, dict):
        return None
    for key in ("id", "personId"):
        v = resp.get(key)
        if isinstance(v, int) and v > 0:
            return v
    inner = resp.get("person") if isinstance(resp.get("person"), dict) else None
    if isinstance(inner, dict):
        v2 = inner.get("id")
        if isinstance(v2, int) and v2 > 0:
            return v2
    return None


def main() -> int:
    session = get_session()
    if not session.get("id_token"):
        print("No ~/.acs-cli/session.json — run: python -m cli.acs auth login", file=sys.stderr)
        return 2

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
    out_dir = _BACKEND_ROOT / "e2e_runs" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    meta: dict[str, object] = {"run_id": run_id, "started_at": datetime.now(timezone.utc).isoformat()}

    def log(msg: str) -> None:
        print(msg, flush=True)
        lines.append(msg)

    try:
        session = _ensure_fresh_token(dict(session))
    except NotLoggedIn as e:
        print(str(e), file=sys.stderr)
        return 3

    uid = _uid_from_token(session["id_token"])
    meta["uid"] = uid
    _save(out_dir, "_meta", meta)

    log(f"=== E2E lead intel run {run_id} uid={uid[:8]}… ===")

    # --- Health ---
    st, body = _req(session, "GET", "/health", json_body=None, timeout=30)
    _save(out_dir, "01_health", {"http": st, "body": body})
    log(f"01 health HTTP {st}")

    # --- FUB status ---
    st, body = _req(session, "GET", "/integrations/followupboss/status", timeout=30)
    _save(out_dir, "02_fub_status", {"http": st, "body": body})
    log(f"02 fub/status HTTP {st}")
    if st >= 400:
        log("ERROR: FUB not reachable — abort.")
        _write_summary(out_dir, lines, meta)
        return 4

    # --- Read profile (guardrail restore) ---
    st, body = _req(session, "POST", "/db/read", json_body={"path": f"Realtors/{uid}"}, timeout=30)
    _save(out_dir, "03_profile_read_before", {"http": st, "body": body})
    prev_guard = None
    if st == 200 and isinstance(body, dict):
        data = body.get("data")
        if isinstance(data, dict) and "guardrailLevel" in data:
            prev_guard = data.get("guardrailLevel")
    meta["guardrailLevel_before"] = prev_guard
    log(f"03 profile read HTTP {st} guardrailLevel_before={prev_guard!r}")

    # --- Hands-on for CRM notes (restore after) ---
    if st == 200 and isinstance(body, dict) and isinstance(body.get("data"), dict):
        merged = {**body["data"], "guardrailLevel": 1}
        st_g, body_g = _req(
            session,
            "POST",
            "/db/upsert",
            json_body={"path": f"Realtors/{uid}", "data": merged, "merge": True},
            timeout=30,
        )
        _save(out_dir, "04_profile_hands_on", {"http": st_g, "body": body_g})
        log(f"04 profile hands-on HTTP {st_g}")

    # --- Refresh FUB OAuth (fixes expired-access-token on people/*) ---
    st_fr, body_fr = _req(session, "POST", "/integrations/followupboss/refresh", json_body={}, timeout=60)
    _save(out_dir, "04b_fub_oauth_refresh", {"http": st_fr, "body": body_fr})
    log(f"04b fub/oauth refresh HTTP {st_fr}")

    # --- Create person in FUB (webhook: peopleCreated → enrichment + scoring) ---
    ts = uuid.uuid4().hex[:10]
    email = f"acs.leadintel.{ts}@example.com"
    create_body = {
        "firstName": "ACS",
        "lastName": f"LeadIntel-{ts}",
        "emails": [{"value": email}],
        "tags": ["acs-e2e", "lead-intel-probe"],
        "stage": "New Lead",
        "source": "Other",
    }
    st, body = _req(
        session,
        "POST",
        "/integrations/followupboss/people/create",
        json_body=create_body,
        timeout=60,
    )
    _save(out_dir, "05_people_create", {"http": st, "request": create_body, "body": body})
    log(f"05 people/create HTTP {st}")
    pid = _person_id_from_create(body if isinstance(body, dict) else {})
    if not pid:
        log("ERROR: could not parse person id from create response")
        meta["person_id"] = None
        _write_summary(out_dir, lines, meta)
        return 5
    meta["person_id"] = pid
    meta["probe_email"] = email
    log(f"    person_id={pid} email={email}")

    ic_path = f"Realtors/{uid}/InternalClients/{internal_client_doc_id(provider='followupboss', external_person_id=str(pid))}"
    lead_path = f"Realtors/{uid}/Leads/{canonical_lead_doc_id(pid)}"
    meta["internal_clients_path"] = ic_path
    meta["leads_path"] = lead_path

    def snapshot_intel(step: str, wait_label: str) -> None:
        time.sleep(2)
        st_i, b_i = _req(session, "POST", "/db/read", json_body={"path": ic_path}, timeout=30)
        st_l, b_l = _req(session, "POST", "/db/read", json_body={"path": lead_path}, timeout=30)
        _save(out_dir, step + "_internal_clients", {"http": st_i, "body": b_i, "after": wait_label})
        _save(out_dir, step + "_leads", {"http": st_l, "body": b_l, "after": wait_label})
        log(f"{step} db/read internal HTTP {st_i} leads HTTP {st_l}")

    # --- Wait for FUB webhooks ---
    wait1 = 35
    log(f"06 sleeping {wait1}s for peopleCreated webhooks…")
    time.sleep(wait1)
    snapshot_intel("07", f"{wait1}s after create")

    # --- Tag change (webhook; may not change acsIntel — not a default delta field) ---
    st, body = _req(
        session,
        "POST",
        "/integrations/followupboss/people/tags/add",
        json_body={"personId": pid, "tags": [f"acs-e2e-{ts[:6]}"]},
        timeout=60,
    )
    _save(out_dir, "08_tags_add", {"http": st, "body": body})
    log(f"08 tags/add HTTP {st}")
    wait2 = 25
    log(f"09 sleeping {wait2}s after tags…")
    time.sleep(wait2)
    snapshot_intel("10", f"{wait2}s after tags")

    # --- Material field change (peopleUpdated → intel_delta + scoring) ---
    st, body = _req(
        session,
        "POST",
        "/integrations/followupboss/people/get",
        json_body={"personId": pid},
        timeout=45,
    )
    prev_last = ""
    if st == 200 and isinstance(body, dict):
        prev_last = str(body.get("lastName") or "")
    new_last = (prev_last or "LeadIntel") + "-delta" + uuid.uuid4().hex[:4]
    st_u, body_u = _req(
        session,
        "POST",
        "/integrations/followupboss/people/update",
        json_body={"personId": pid, "lastName": new_last},
        timeout=60,
    )
    _save(out_dir, "11_people_update_lastname", {"http": st_u, "request": {"lastName": new_last}, "body": body_u})
    log(f"11 people/update lastName HTTP {st_u} -> {new_last!r}")
    wait3 = 35
    log(f"12 sleeping {wait3}s after lastName update…")
    time.sleep(wait3)
    snapshot_intel("13", f"{wait3}s after lastName")

    # --- Synchronous webhook_test (workflow_debug, no duplicate eventId) ---
    ev = "peopleUpdated"
    wh_body = fub_webhook_minimal_body(
        event=normalize_fub_webhook_event(ev),
        person_id=pid,
        event_id=f"e2e-manual-{uuid.uuid4().hex[:12]}",
    )
    st, body = _req(
        session,
        "POST",
        "/integrations/followupboss/webhook_test",
        json_body=wh_body,
        timeout=180,
    )
    _save(out_dir, "14_webhook_test_people_updated", {"http": st, "request": wh_body, "body": body})
    log(f"14 webhook_test peopleUpdated HTTP {st}")
    snapshot_intel("15", "after webhook_test")

    meta["finished_at"] = datetime.now(timezone.utc).isoformat()
    meta["person_id"] = pid
    _save(out_dir, "_meta", meta)

    # --- Isolate intel_delta core error (workflow_debug shows last workflow only in multi-run) ---
    wh_diag = fub_webhook_minimal_body(
        event="peopleUpdated",
        person_id=int(pid),
        event_id=f"e2e-diag-intel-{uuid.uuid4().hex[:12]}",
    )
    st_d, body_d = _req(
        session,
        "POST",
        "/integrations/followupboss/webhook_test?workflowId=contact.intel_delta_v1",
        json_body=wh_diag,
        timeout=180,
    )
    _save(out_dir, "16_webhook_test_intel_delta_only", {"http": st_d, "request": wh_diag, "body": body_d})
    log(f"16 webhook_test intel_delta only HTTP {st_d}")

    # --- Quick analysis hints ---
    hints = _analyze_artifacts(out_dir)
    _save(out_dir, "_analysis_hints", hints)
    log("--- analysis hints ---")
    for k, v in hints.items():
        log(f"  {k}: {v}")

    # --- Restore guardrail ---
    if prev_guard is not None:
        st_r, body_r = _req(session, "POST", "/db/read", json_body={"path": f"Realtors/{uid}"}, timeout=30)
        if st_r == 200 and isinstance(body_r, dict) and isinstance(body_r.get("data"), dict):
            merged_r = {**body_r["data"], "guardrailLevel": prev_guard}
            st_u2, body_u2 = _req(
                session,
                "POST",
                "/db/upsert",
                json_body={"path": f"Realtors/{uid}", "data": merged_r, "merge": True},
                timeout=30,
            )
            _save(out_dir, "17_profile_restore", {"http": st_u2, "body": body_u2})
            log(f"17 profile restore guardrailLevel={prev_guard} HTTP {st_u2}")

    _write_summary(out_dir, lines, meta)
    log(f"Done. Artifacts: {out_dir}")
    return 0


def _analyze_artifacts(out_dir: Path) -> dict[str, object]:
    hints: dict[str, object] = {}
    p16 = out_dir / "16_webhook_test_intel_delta_only.json"
    if p16.exists():
        raw16 = json.loads(p16.read_text(encoding="utf-8"))
        b16 = raw16.get("body") if isinstance(raw16.get("body"), dict) else {}
        wd16 = b16.get("workflow_debug") if isinstance(b16.get("workflow_debug"), dict) else {}
        st16 = wd16.get("state") if isinstance(wd16.get("state"), dict) else {}
        core16 = st16.get("metadata_core") if isinstance(st16.get("metadata_core"), dict) else {}
        det = str(core16.get("detail") or "")
        hints["intel_delta_only_core_http"] = wd16.get("core_http_status")
        if "NameError" in det:
            hints["intel_delta_failure_class"] = "NameError (fixed in repo: pipeline._pipeline_meta lazy param)"
        elif det:
            hints["intel_delta_traceback_tail"] = det[-500:]

    p14 = out_dir / "14_webhook_test_people_updated.json"
    if p14.exists():
        raw = json.loads(p14.read_text(encoding="utf-8"))
        body = raw.get("body") if isinstance(raw.get("body"), dict) else {}
        wd = body.get("workflow_debug") if isinstance(body.get("workflow_debug"), dict) else {}
        hints["webhook_test_workflow_debug_present"] = bool(wd)
        hints["webhook_dispatch"] = body.get("webhook_dispatch")
        st = wd.get("state") if isinstance(wd.get("state"), dict) else {}
        pol = st.get("metadata_execution_policy") if isinstance(st.get("metadata_execution_policy"), dict) else {}
        hints["volatile_external_allowed_in_debug"] = pol.get("volatile_external_allowed")
        audit = None
        if isinstance(st, dict):
            meta = st.get("metadata") if isinstance(st.get("metadata"), dict) else {}
            audit = meta.get("workflowAudit")
        hints["workflow_audit_nodes_count"] = (
            len(audit.get("nodes", [])) if isinstance(audit, dict) and isinstance(audit.get("nodes"), list) else None
        )

    def _intel_summary(path: Path) -> dict[str, object] | None:
        if not path.exists():
            return None
        j = json.loads(path.read_text(encoding="utf-8"))
        b = j.get("body") if isinstance(j.get("body"), dict) else {}
        data = b.get("data") if isinstance(b.get("data"), dict) else {}
        ai = data.get("acsIntel") if isinstance(data.get("acsIntel"), dict) else {}
        return {
            "http": j.get("http"),
            "lastEnrichmentTier": ai.get("lastEnrichmentTier"),
            "lastEnrichedAt": ai.get("lastEnrichedAt"),
            "summary_len": len(str(ai.get("lastWebSummary") or "")),
        }

    hints["intel_after_create"] = _intel_summary(out_dir / "07_internal_clients.json")
    hints["intel_after_tags"] = _intel_summary(out_dir / "10_internal_clients.json")
    hints["intel_after_lastname"] = _intel_summary(out_dir / "13_internal_clients.json")
    hints["intel_after_webhook_test"] = _intel_summary(out_dir / "15_internal_clients.json")
    return hints


def _write_summary(out_dir: Path, lines: list[str], meta: dict[str, object]) -> None:
    p = out_dir / "SUMMARY.md"
    with p.open("w", encoding="utf-8") as f:
        f.write("# Lead intelligence E2E run\n\n")
        f.write(f"- run_id: `{meta.get('run_id')}`\n")
        f.write(f"- uid: `{meta.get('uid')}`\n")
        f.write(f"- person_id: `{meta.get('person_id')}`\n")
        f.write(f"- probe_email: `{meta.get('probe_email')}`\n")
        f.write(f"- internal_clients: `{meta.get('internal_clients_path')}`\n")
        f.write(f"- leads: `{meta.get('leads_path')}`\n")
        f.write(f"- guardrailLevel_before: `{meta.get('guardrailLevel_before')}`\n\n")
        f.write("## Log\n\n```\n")
        f.write("\n".join(lines))
        f.write("\n```\n")


if __name__ == "__main__":
    raise SystemExit(main())

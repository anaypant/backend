#!/usr/bin/env python3
"""
End-to-end lead intelligence + quality harness against a deployed ACS gateway.

Fetches **full** outputs: FUB person + notes, Firestore ``InternalClients`` (``acsIntel``),
``Leads`` (score), optional ``BillingUsage``. Writes per-step JSON, ``local_mirror/`` copies,
``ENRICHMENT_QUALITY.md`` (how good the enrichment is — rubric + excerpts), and updates
``backend/local_test_mirror/lead_intel_last_enriched_contact.json``.

Uses ~/.acs-cli/session.json (refreshes Firebase token if needed).

Run from ``backend/``::

    python scripts/e2e_lead_intel_deployed.py
    python scripts/e2e_lead_intel_deployed.py --stress --poll-intel-seconds 180
    python scripts/e2e_lead_intel_deployed.py --preserve-guardrail --quality-warnings-only

Exit codes: 0 success, 2 auth/config, 3 FUB/person failure, 4 quality hard-fail, 5 HTTP gate.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

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
    (out_dir / f"{name}.json").write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")


def _billing_path(uid: str) -> str:
    ym = datetime.now(timezone.utc).strftime("%Y-%m")
    return f"Realtors/{uid}/BillingUsage/{ym}"


def fetch_enriched_snapshot(
    session: dict,
    uid: str,
    pid: int,
    ic_path: str,
    lead_path: str,
) -> dict[str, Any]:
    captured = datetime.now(timezone.utc).isoformat()
    st_p, person = _req(
        session,
        "POST",
        "/integrations/followupboss/people/get",
        json_body={"personId": pid},
        timeout=60,
    )
    st_n, notes_raw = _req(
        session,
        "POST",
        "/integrations/followupboss/notes/list",
        json_body={"personId": pid, "limit": 100, "offset": 0},
        timeout=60,
    )
    st_i, ic_raw = _req(session, "POST", "/db/read", json_body={"path": ic_path}, timeout=30)
    st_l, lead_raw = _req(session, "POST", "/db/read", json_body={"path": lead_path}, timeout=30)
    st_b, bill_raw = _req(session, "POST", "/db/read", json_body={"path": _billing_path(uid)}, timeout=30)

    ic_data = ic_raw.get("data") if isinstance(ic_raw, dict) else {}
    acs_intel = ic_data.get("acsIntel") if isinstance(ic_data, dict) and isinstance(ic_data.get("acsIntel"), dict) else {}
    notes_list_out: list[Any] = []
    if isinstance(notes_raw, dict):
        notes_list_out = notes_raw.get("notes") if isinstance(notes_raw.get("notes"), list) else []

    lead_data = lead_raw.get("data") if isinstance(lead_raw, dict) else {}
    bill_data = bill_raw.get("data") if isinstance(bill_raw, dict) else {}

    snap_sub: dict[str, Any] = {}
    if isinstance(acs_intel.get("snapshot"), dict):
        s = acs_intel["snapshot"]
        snap_sub = {
            "display_name": s.get("display_name"),
            "person_id": s.get("person_id"),
            "emails": s.get("emails"),
            "phones": s.get("phones"),
        }

    billing_qe: dict[str, Any] = {}
    if isinstance(bill_data, dict):
        for k in (
            "workflowRunCounts",
            "lazySnapshotRuns",
            "intelDeltaRuns",
            "fullSnapshotRuns",
            "lastUsageTier",
            "lastWorkflowId",
            "spentUsd",
            "searchApiCalls",
            "lastUpdatedSearch",
            "llmTokensInEstimated",
            "llmTokensOutEstimated",
            "enrichmentsTotal",
            "enrichmentsPremium",
            "enrichmentsStandard",
        ):
            if k in bill_data:
                billing_qe[k] = bill_data[k]

    probe_email_status = None
    if isinstance(person.get("emails"), list) and person["emails"]:
        e0 = person["emails"][0]
        if isinstance(e0, dict):
            probe_email_status = str(e0.get("status") or "")

    bodies = [
        str(n.get("body") or "")
        for n in notes_list_out
        if isinstance(n, dict) and isinstance(n.get("body"), str)
    ]

    return {
        "captured_at": captured,
        "realtor_uid": uid,
        "followupboss_person_id": pid,
        "http": {
            "people_get": st_p,
            "notes_list": st_n,
            "internal_clients_read": st_i,
            "leads_read": st_l,
            "billing_usage_read": st_b,
        },
        "followupboss_person": person if isinstance(person, dict) else {},
        "followupboss_notes": notes_list_out,
        "firestore_internal_clients": ic_raw if isinstance(ic_raw, dict) else {},
        "firestore_leads": lead_raw if isinstance(lead_raw, dict) else {},
        "firestore_billing_usage": bill_raw if isinstance(bill_raw, dict) else {},
        "quality_extracts": {
            "acs_note_bodies": bodies,
            "fub_note_count": len(notes_list_out),
            "acs_note_char_max": max((len(b) for b in bodies), default=0),
            "lastWebSummary_preview": str(acs_intel.get("lastWebSummary") or "")[:4000],
            "lastWebSummary_len": len(str(acs_intel.get("lastWebSummary") or "")),
            "lastEnrichmentTier": acs_intel.get("lastEnrichmentTier"),
            "lastEnrichedAt": acs_intel.get("lastEnrichedAt"),
            "glydeScore": lead_data.get("glydeScore") if isinstance(lead_data, dict) else None,
            "glydeIsHot": lead_data.get("glydeIsHot") if isinstance(lead_data, dict) else None,
            "glydeScoreUpdatedAt": lead_data.get("glydeScoreUpdatedAt") if isinstance(lead_data, dict) else None,
            "snapshot_extract": snap_sub,
            "billing_usage_extract": billing_qe,
            "probe_primary_email_status": probe_email_status,
        },
    }


def poll_until_intel_doc(
    session: dict,
    ic_path: str,
    *,
    deadline_s: float,
    poll_s: float,
    log,
) -> tuple[int, object]:
    deadline = time.time() + deadline_s
    last_st, last_body = 404, {}
    while time.time() < deadline:
        st, body = _req(session, "POST", "/db/read", json_body={"path": ic_path}, timeout=30)
        last_st, last_body = st, body
        if st == 200 and isinstance(body, dict):
            data = body.get("data")
            if isinstance(data, dict) and isinstance(data.get("acsIntel"), dict):
                ai = data["acsIntel"]
                if ai.get("lastEnrichedAt") or ai.get("snapshot"):
                    return st, body
        remain = int(deadline - time.time())
        log(f"    … polling InternalClients ({remain}s left) http={st}")
        time.sleep(poll_s)
    return last_st, last_body


def stress_webhook_burst(
    session: dict,
    pid: int,
    out_dir: Path,
    log,
    *,
    iterations: int,
) -> None:
    for i in range(iterations):
        body = fub_webhook_minimal_body(
            event="peopleUpdated",
            person_id=int(pid),
            event_id=f"e2e-stress-{i}-{uuid.uuid4().hex[:12]}",
        )
        st, resp = _req(session, "POST", "/integrations/followupboss/webhook_test", json_body=body, timeout=180)
        _save(out_dir, f"stress_{i + 1:02d}_webhook_people_updated", {"http": st, "request": body, "body": resp})
        log(f"stress#{i + 1} webhook_test peopleUpdated HTTP {st}")
        if st >= 400:
            raise RuntimeError(f"stress webhook HTTP {st}")
        dispatch = resp.get("webhook_dispatch") if isinstance(resp, dict) else []
        if not isinstance(dispatch, list):
            raise RuntimeError("stress: missing webhook_dispatch")
        for row in dispatch:
            if isinstance(row, dict) and int(row.get("core_http_status") or 500) >= 400:
                raise RuntimeError(f"stress: core failure {row}")


def evaluate_quality(
    snap: dict[str, Any],
    *,
    hands_on_effective: bool,
    stress: bool,
) -> dict[str, Any]:
    fails: list[str] = []
    warns: list[str] = []
    http = snap.get("http") or {}
    for k, v in http.items():
        if isinstance(v, int) and v >= 400:
            if k == "billing_usage_read":
                warns.append(f"billing doc HTTP {v} (optional)")
            else:
                fails.append(f"HTTP {v} on {k}")

    qe = snap.get("quality_extracts") or {}
    bodies: list[str] = [b for b in (qe.get("acs_note_bodies") or []) if isinstance(b, str)]

    if hands_on_effective:
        if not any("ACS" in b for b in bodies):
            fails.append("hands-on: no FUB note body contains 'ACS' (expected createNote from workflows)")
        if not any(len(b) > 80 for b in bodies if "ACS" in b):
            warns.append("hands-on: no long ACS note (>80 chars) — notes may be very short")

    g = qe.get("glydeScore")
    if isinstance(g, int):
        if g < 0 or g > 100:
            fails.append(f"glydeScore out of 0..100: {g}")
    elif g is not None:
        warns.append(f"glydeScore not int: {g!r}")

    slen = int(qe.get("lastWebSummary_len") or 0)
    if slen == 0:
        warns.append("lastWebSummary empty — common for lazy + low-signal email; not a hard fail")
    if stress and slen < 40:
        warns.append("stress: lastWebSummary < 40 chars — research may be starved or blocked")

    return {"passed": len(fails) == 0, "failures": fails, "warnings": warns}


def _tier_label(tier: object) -> str:
    t = str(tier or "").strip().lower()
    if not t:
        return "unknown"
    if t == "lazy":
        return "lazy (minimal web research by design)"
    if t == "full":
        return "full snapshot"
    if "intel_delta" in t or t == "intel_delta":
        return "intel_delta (material-field refresh + optional mini-research)"
    return str(tier)


def _summary_depth_label(n: int) -> str:
    if n <= 0:
        return "empty"
    if n < 40:
        return "thin"
    if n < 200:
        return "moderate"
    return "rich"


def _note_value_label(bodies: list[str]) -> str:
    if not bodies:
        return "none (no FUB notes returned)"
    joined = " ".join(bodies)
    if len(joined) < 40:
        return "minimal (very short)"
    if len(joined) < 120:
        return "adequate (short update)"
    if "little additional public context" in joined.lower():
        return "adequate + honest low-signal wording"
    return "substantive"


def _write_enrichment_quality_report(
    backend_root: Path,
    out_dir: Path,
    final_snap: dict[str, Any],
    quality: dict[str, Any],
    meta: dict[str, Any],
) -> None:
    """Human-readable enrichment / product-quality view (not pass/fail gates)."""
    qe: dict[str, Any] = dict(final_snap.get("quality_extracts") or {})

    notes_raw = final_snap.get("followupboss_notes")
    if isinstance(notes_raw, list) and "acs_note_bodies" not in qe:
        qe["acs_note_bodies"] = [
            str(n.get("body") or "")
            for n in notes_raw
            if isinstance(n, dict) and isinstance(n.get("body"), str)
        ]
    if "fub_note_count" not in qe and isinstance(notes_raw, list):
        qe["fub_note_count"] = len(notes_raw)
    bodies = [b for b in (qe.get("acs_note_bodies") or []) if isinstance(b, str)]
    if "acs_note_char_max" not in qe:
        qe["acs_note_char_max"] = max((len(b) for b in bodies), default=0)

    if not qe.get("billing_usage_extract"):
        bill_raw = final_snap.get("firestore_billing_usage")
        bd = bill_raw.get("data") if isinstance(bill_raw, dict) else None
        if isinstance(bd, dict):
            be: dict[str, Any] = {}
            for k in (
                "workflowRunCounts",
                "lazySnapshotRuns",
                "intelDeltaRuns",
                "fullSnapshotRuns",
                "lastUsageTier",
                "lastWorkflowId",
                "spentUsd",
                "searchApiCalls",
                "lastUpdatedSearch",
                "llmTokensInEstimated",
                "llmTokensOutEstimated",
                "enrichmentsTotal",
                "enrichmentsPremium",
                "enrichmentsStandard",
            ):
                if k in bd:
                    be[k] = bd[k]
            if be:
                qe["billing_usage_extract"] = be

    if not qe.get("snapshot_extract"):
        ic = final_snap.get("firestore_internal_clients")
        data = ic.get("data") if isinstance(ic, dict) else None
        ai = data.get("acsIntel") if isinstance(data, dict) else None
        snap = ai.get("snapshot") if isinstance(ai, dict) and isinstance(ai.get("snapshot"), dict) else {}
        if isinstance(snap, dict):
            qe["snapshot_extract"] = {
                "display_name": snap.get("display_name"),
                "person_id": snap.get("person_id"),
                "emails": snap.get("emails"),
                "phones": snap.get("phones"),
            }

    if qe.get("probe_primary_email_status") is None:
        person = final_snap.get("followupboss_person") if isinstance(final_snap.get("followupboss_person"), dict) else {}
        em = person.get("emails")
        if isinstance(em, list) and em and isinstance(em[0], dict):
            qe["probe_primary_email_status"] = str(em[0].get("status") or "")

    person = final_snap.get("followupboss_person") if isinstance(final_snap.get("followupboss_person"), dict) else {}
    bodies: list[str] = [b for b in (qe.get("acs_note_bodies") or []) if isinstance(b, str)]
    slen = int(qe.get("lastWebSummary_len") or 0)
    tier = qe.get("lastEnrichmentTier")
    g = qe.get("glydeScore")
    snap = qe.get("snapshot_extract") if isinstance(qe.get("snapshot_extract"), dict) else {}
    bill = qe.get("billing_usage_extract") if isinstance(qe.get("billing_usage_extract"), dict) else {}
    fub_name = str(person.get("name") or person.get("displayName") or "").strip()
    snap_name = str(snap.get("display_name") or "").strip()
    aligned = bool(
        fub_name
        and snap_name
        and fub_name.replace(" ", "").lower() == snap_name.replace(" ", "").lower()
    )

    lines: list[str] = [
        "# Enrichment quality — E2E snapshot",
        "",
        f"- **run_id:** `{meta.get('run_id')}`",
        f"- **person_id:** `{meta.get('person_id')}`",
        f"- **probe_email:** `{meta.get('probe_email')}`",
        f"- **captured_at:** `{final_snap.get('captured_at')}`",
        "",
        "## 1. Verdict (product signal, not CI gates)",
        "",
        "| Signal | Value | Interpretation |",
        "|--------|-------|----------------|",
        f"| Stored tier | `{tier}` | {_tier_label(tier)} |",
        f"| `lastWebSummary` length | **{slen}** | {_summary_depth_label(slen)} — empty is common for **invalid/example email** + lazy tier |",
        f"| FUB notes (ACS) | **{qe.get('fub_note_count', 0)}** note(s), max **{qe.get('acs_note_char_max', 0)}** chars | {_note_value_label(bodies)} |",
        f"| `glydeScore` | **{g}** | Lead scoring output present (0–100 scale); rationale lives in workflow metadata, not always in Firestore |",
        f"| Snapshot vs FUB name | **{'aligned' if aligned else 'check'}** | Firestore `acsIntel.snapshot.display_name` vs FUB `name` |",
        f"| Primary email status (FUB) | `{qe.get('probe_primary_email_status')}` | Invalid → web research rarely finds real identity |",
        "",
        "## 2. Rubric (how good was this enrichment for a realtor?)",
        "",
        "| Expectation | Grade | Notes |",
        "|-------------|-------|-------|",
    ]

    # Heuristic grades A–F style as words
    tier_s = str(tier or "").lower()
    tier_grade = "Strong" if tier_s in ("intel_delta", "full") else ("OK" if tier_s == "lazy" else "Unknown")
    lines.append(f"| Pipeline ran end-to-end | **Strong** | Webhooks + workflows + Firestore reads succeeded |")
    lines.append(f"| Tiering behaves | **{tier_grade}** | `lastEnrichmentTier` from final snapshot |")
    sum_grade = "Low" if slen == 0 else ("OK" if slen < 200 else "Strong")
    lines.append(f"| Research summary usefulness | **{sum_grade}** | Driven by signal strength + tier + email validity |")
    note_grade = "Low" if not bodies else ("OK" if len(max(bodies, key=len, default="")) < 80 else "Strong")
    lines.append(f"| CRM note (delta / ACS) | **{note_grade}** | First-party FUB `notes/list` bodies |")
    lines.append(f"| Score actionable | **{'OK' if isinstance(g, int) else 'Unknown'}** | Number without qualitative rationale in this export |")

    lines.extend(
        [
            "",
            "## 3. What to read in artifacts",
            "",
            "- **`18_final_enriched_snapshot.json`** — full FUB person, notes, `InternalClients` + `Leads` + optional `BillingUsage`.",
            "- **`local_mirror/enriched_contact_full.json`** — same payload.",
            "- **`_analysis_hints.json`** — tier + summary length after each phase (07/10/13/15).",
            "",
            "## 4. ACS / delta note excerpts (FUB)",
            "",
        ]
    )
    if not bodies:
        lines.append("_No note bodies in snapshot._")
    else:
        for i, b in enumerate(bodies[:5], 1):
            lines.append(f"### Note {i}")
            lines.append("")
            lines.append("```")
            lines.append(b[:8000])
            lines.append("```")
            lines.append("")

    prev = str(qe.get("lastWebSummary_preview") or "").strip()
    lines.extend(["## 5. Web research summary (`acsIntel.lastWebSummary`)", ""])
    if not prev:
        lines.append("_Empty in this run._")
        lines.append("")
    else:
        lines.append("```")
        lines.append(prev[:8000])
        lines.append("```")
        lines.append("")

    lines.extend(["## 6. Stored snapshot (identity slice)", "", "```json"])
    lines.append(json.dumps(snap, indent=2, default=str) if snap else "{}")
    lines.append("```")
    lines.append("")

    lines.extend(["## 7. Usage meter (month doc, if present)", "", "```json"])
    lines.append(json.dumps(bill, indent=2, default=str) if bill else "{}")
    lines.append("```")
    lines.append("")

    lines.extend(
        [
            "## 8. Automated quality warnings (from harness)",
            "",
            "```json",
            json.dumps(quality.get("warnings") or [], indent=2, default=str),
            "```",
            "",
            "**Tip:** For a richer `lastWebSummary`, re-run with `--business-email` set to a **reachable business domain** (or `ACS_E2E_BUSINESS_EMAIL`) so web research has real anchors.",
            "",
        ]
    )

    text = "\n".join(lines)
    (out_dir / "ENRICHMENT_QUALITY.md").write_text(text, encoding="utf-8")
    lm = out_dir / "local_mirror"
    lm.mkdir(parents=True, exist_ok=True)
    (lm / "ENRICHMENT_QUALITY.md").write_text(text, encoding="utf-8")
    mirror = backend_root / "local_test_mirror" / "lead_intel_last_enrichment_quality.md"
    mirror.parent.mkdir(parents=True, exist_ok=True)
    mirror.write_text(text, encoding="utf-8")


def _write_local_mirror(backend_root: Path, out_dir: Path, final_snap: dict[str, Any], meta: dict[str, Any]) -> None:
    lm = out_dir / "local_mirror"
    lm.mkdir(parents=True, exist_ok=True)
    (lm / "enriched_contact_full.json").write_text(json.dumps(final_snap, indent=2, default=str), encoding="utf-8")
    (lm / "run_meta.json").write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")

    mirror_dir = backend_root / "local_test_mirror"
    mirror_dir.mkdir(parents=True, exist_ok=True)
    ptr = {
        "run_id": meta.get("run_id"),
        "artifact_dir": str(out_dir.resolve()),
        "person_id": meta.get("person_id"),
        "probe_email": meta.get("probe_email"),
        "captured_at": final_snap.get("captured_at"),
    }
    (mirror_dir / "lead_intel_last_run.json").write_text(json.dumps(ptr, indent=2), encoding="utf-8")
    (mirror_dir / "lead_intel_last_enriched_contact.json").write_text(
        json.dumps(final_snap, indent=2, default=str),
        encoding="utf-8",
    )


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


def _analyze_dispatch(out_dir: Path, fname: str) -> dict[str, Any] | None:
    p = out_dir / fname
    if not p.exists():
        return None
    raw = json.loads(p.read_text(encoding="utf-8"))
    body = raw.get("body") if isinstance(raw.get("body"), dict) else {}
    return body.get("webhook_dispatch") if isinstance(body.get("webhook_dispatch"), list) else None


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
            hints["intel_delta_failure_class"] = "NameError"
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


def _write_summary(out_dir: Path, lines: list[str], meta: dict[str, Any], quality: dict[str, Any]) -> None:
    p = out_dir / "SUMMARY.md"
    qj = out_dir / "QUALITY_GATES.json"
    qj.write_text(json.dumps(quality, indent=2, default=str), encoding="utf-8")
    with p.open("w", encoding="utf-8") as f:
        f.write("# Lead intelligence E2E run\n\n")
        f.write(f"- run_id: `{meta.get('run_id')}`\n")
        f.write(f"- uid: `{meta.get('uid')}`\n")
        f.write(f"- person_id: `{meta.get('person_id')}`\n")
        f.write(f"- probe_email: `{meta.get('probe_email')}`\n")
        f.write(f"- internal_clients: `{meta.get('internal_clients_path')}`\n")
        f.write(f"- leads: `{meta.get('leads_path')}`\n")
        f.write(f"- guardrailLevel_before: `{meta.get('guardrailLevel_before')}`\n")
        f.write(f"- local_mirror: `{out_dir / 'local_mirror'}`\n")
        f.write(f"- workspace_copy: `{_BACKEND_ROOT / 'local_test_mirror'}`\n\n")
        f.write("## Enrichment quality (human-readable)\n\n")
        f.write("See **[ENRICHMENT_QUALITY.md](./ENRICHMENT_QUALITY.md)** for rubric, excerpts, usage slice, and interpretation.\n\n")
        f.write("## Quality gates\n\n```json\n")
        f.write(json.dumps(quality, indent=2, default=str))
        f.write("\n```\n\n## Log\n\n```\n")
        f.write("\n".join(lines))
        f.write("\n```\n")


def run(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Lead intelligence E2E + quality harness")
    ap.add_argument("--stress", action="store_true", help="Longer polls + extra webhook_test burst (core load)")
    ap.add_argument(
        "--business-email",
        default="",
        help="Override probe email (else ACS_E2E_BUSINESS_EMAIL env, else acs.leadintel.{id}@example.com)",
    )
    ap.add_argument("--poll-intel-seconds", type=float, default=120.0, help="Max wait for InternalClients acsIntel")
    ap.add_argument("--preserve-guardrail", action="store_true", help="Do not force hands-on / restore profile")
    ap.add_argument(
        "--quality-warnings-only",
        action="store_true",
        help="Do not exit non-zero on quality failures (still exit on HTTP / dispatch errors)",
    )
    ap.add_argument(
        "--render-quality-report",
        metavar="PATH",
        default="",
        help="Only write ENRICHMENT_QUALITY.md from a saved 18_final_enriched_snapshot.json (no network)",
    )
    args = ap.parse_args(argv)

    rq = (args.render_quality_report or "").strip()
    if rq:
        p = Path(rq)
        if not p.is_absolute():
            p = (_BACKEND_ROOT / p).resolve()
        if not p.is_file():
            print(f"Not found: {p}", file=sys.stderr)
            return 2
        snap = json.loads(p.read_text(encoding="utf-8"))
        out_dir = p.parent
        meta_path = out_dir / "_meta.json"
        meta: dict[str, Any] = {
            "run_id": out_dir.name,
            "person_id": snap.get("followupboss_person_id"),
            "probe_email": "",
        }
        if meta_path.is_file():
            try:
                meta.update(json.loads(meta_path.read_text(encoding="utf-8")))
            except Exception:
                pass
        qpath = out_dir / "QUALITY_GATES.json"
        if qpath.is_file():
            try:
                quality = json.loads(qpath.read_text(encoding="utf-8"))
            except Exception:
                quality = {"passed": True, "failures": [], "warnings": []}
        else:
            prev_guard = meta.get("guardrailLevel_before")
            quality = evaluate_quality(
                snap,
                hands_on_effective=bool(prev_guard == 1),
                stress=False,
            )
        _write_enrichment_quality_report(_BACKEND_ROOT, out_dir, snap, quality, meta)
        print(f"Wrote {out_dir / 'ENRICHMENT_QUALITY.md'}")
        return 0

    session = get_session()
    if not session.get("id_token"):
        print("No ~/.acs-cli/session.json — run: python -m cli.acs auth login", file=sys.stderr)
        return 2

    lines: list[str] = []

    def log(msg: str) -> None:
        print(msg, flush=True)
        lines.append(msg)

    try:
        session = _ensure_fresh_token(dict(session))
    except NotLoggedIn as e:
        print(str(e), file=sys.stderr)
        return 2

    uid = _uid_from_token(session["id_token"])
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
    out_dir = _BACKEND_ROOT / "e2e_runs" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    meta: dict[str, Any] = {"run_id": run_id, "started_at": datetime.now(timezone.utc).isoformat(), "uid": uid}
    _save(out_dir, "_meta", meta)

    poll_deadline = max(60.0, float(args.poll_intel_seconds))
    if args.stress:
        poll_deadline = max(poll_deadline, 180.0)

    log(f"=== E2E lead intel run {run_id} uid={uid[:8]}… === stress={args.stress} poll={poll_deadline}s ===")

    st, body = _req(session, "GET", "/health", json_body=None, timeout=30)
    _save(out_dir, "01_health", {"http": st, "body": body})
    log(f"01 health HTTP {st}")

    st, body = _req(session, "GET", "/integrations/followupboss/status", timeout=30)
    _save(out_dir, "02_fub_status", {"http": st, "body": body})
    log(f"02 fub/status HTTP {st}")
    if st >= 400:
        return 3

    st, body = _req(session, "POST", "/db/read", json_body={"path": f"Realtors/{uid}"}, timeout=30)
    _save(out_dir, "03_profile_read_before", {"http": st, "body": body})
    prev_guard = None
    if st == 200 and isinstance(body, dict):
        data = body.get("data")
        if isinstance(data, dict) and "guardrailLevel" in data:
            prev_guard = data.get("guardrailLevel")
    meta["guardrailLevel_before"] = prev_guard
    log(f"03 profile read HTTP {st} guardrailLevel_before={prev_guard!r}")

    hands_on_effective = False
    if not args.preserve_guardrail and st == 200 and isinstance(body, dict) and isinstance(body.get("data"), dict):
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
        hands_on_effective = st_g < 400
    elif args.preserve_guardrail:
        log("04 profile hands-on SKIPPED (--preserve-guardrail)")
        hands_on_effective = prev_guard == 1

    st_fr, body_fr = _req(session, "POST", "/integrations/followupboss/refresh", json_body={}, timeout=60)
    _save(out_dir, "04b_fub_oauth_refresh", {"http": st_fr, "body": body_fr})
    log(f"04b fub/oauth refresh HTTP {st_fr}")

    ts = uuid.uuid4().hex[:10]
    env_email = (os.environ.get("ACS_E2E_BUSINESS_EMAIL") or "").strip()
    email = (args.business_email or env_email or f"acs.leadintel.{ts}@example.com").strip()
    create_body: dict[str, Any] = {
        "firstName": "ACS",
        "lastName": f"LeadIntel-{ts}",
        "emails": [{"value": email}],
        "tags": ["acs-e2e", "lead-intel-probe"],
        "stage": "New Lead",
        "source": "Other",
    }
    if args.stress:
        create_body["phones"] = [{"value": f"+1555{ts[-7:]}"}]

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
        _write_summary(out_dir, lines, meta, {"passed": False, "failures": ["person_id parse"], "warnings": []})
        return 3

    meta["person_id"] = pid
    meta["probe_email"] = email
    ic_path = f"Realtors/{uid}/InternalClients/{internal_client_doc_id(provider='followupboss', external_person_id=str(pid))}"
    lead_path = f"Realtors/{uid}/Leads/{canonical_lead_doc_id(pid)}"
    meta["internal_clients_path"] = ic_path
    meta["leads_path"] = lead_path
    log(f"    person_id={pid} email={email}")

    def snap(label: str, suffix: str) -> None:
        snap_body = fetch_enriched_snapshot(session, uid, pid, ic_path, lead_path)
        _save(out_dir, f"snapshots_{suffix}_enriched", snap_body)
        log(f"    snapshot {suffix} notes={len(snap_body.get('followupboss_notes') or [])}")

    def snapshot_db_only(step: str, wait_label: str) -> None:
        time.sleep(2)
        st_i, b_i = _req(session, "POST", "/db/read", json_body={"path": ic_path}, timeout=30)
        st_l, b_l = _req(session, "POST", "/db/read", json_body={"path": lead_path}, timeout=30)
        _save(out_dir, f"{step}_internal_clients", {"http": st_i, "body": b_i, "after": wait_label})
        _save(out_dir, f"{step}_leads", {"http": st_l, "body": b_l, "after": wait_label})
        log(f"{step} db/read internal HTTP {st_i} leads HTTP {st_l}")

    wait1 = 50.0 if args.stress else 35.0
    log(f"06 polling intel up to {poll_deadline}s after create (min sleep {wait1}s)…")
    time.sleep(min(15.0, wait1))
    st_pi, _ = poll_until_intel_doc(session, ic_path, deadline_s=poll_deadline, poll_s=3.0, log=log)
    if st_pi != 200:
        time.sleep(max(0.0, wait1 - 15.0))
        st_pi, _ = poll_until_intel_doc(session, ic_path, deadline_s=min(45.0, poll_deadline), poll_s=3.0, log=log)
    snapshot_db_only("07", "after create / poll")
    snap("after_create", "07")

    st, body = _req(
        session,
        "POST",
        "/integrations/followupboss/people/tags/add",
        json_body={"personId": pid, "tags": [f"acs-e2e-{ts[:6]}"]},
        timeout=60,
    )
    _save(out_dir, "08_tags_add", {"http": st, "body": body})
    log(f"08 tags/add HTTP {st}")
    wait2 = 35.0 if args.stress else 25.0
    log(f"09 sleeping {wait2}s after tags…")
    time.sleep(wait2)
    snapshot_db_only("10", f"{wait2}s after tags")
    snap("after_tags", "10")

    st, body = _req(session, "POST", "/integrations/followupboss/people/get", json_body={"personId": pid}, timeout=45)
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
    wait3 = 45.0 if args.stress else 35.0
    log(f"12 sleeping {wait3}s after lastName update…")
    time.sleep(wait3)
    snapshot_db_only("13", f"{wait3}s after lastName")
    snap("after_lastname", "13")

    wh_body = fub_webhook_minimal_body(
        event=normalize_fub_webhook_event("peopleUpdated"),
        person_id=pid,
        event_id=f"e2e-manual-{uuid.uuid4().hex[:12]}",
    )
    st, body = _req(session, "POST", "/integrations/followupboss/webhook_test", json_body=wh_body, timeout=180)
    _save(out_dir, "14_webhook_test_people_updated", {"http": st, "request": wh_body, "body": body})
    log(f"14 webhook_test peopleUpdated HTTP {st}")
    if st >= 400:
        return 5
    disp = _analyze_dispatch(out_dir, "14_webhook_test_people_updated.json")
    if disp and any(isinstance(x, dict) and int(x.get("core_http_status") or 500) >= 400 for x in disp):
        log(f"ERROR: webhook_dispatch failure {disp}")
        return 5

    snapshot_db_only("15", "after webhook_test")
    snap("after_webhook_test", "15")

    if args.stress:
        stress_webhook_burst(session, pid, out_dir, log, iterations=4)

    meta["finished_at"] = datetime.now(timezone.utc).isoformat()
    _save(out_dir, "_meta", meta)

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
    if st_d >= 400:
        return 5

    final_snap = fetch_enriched_snapshot(session, uid, pid, ic_path, lead_path)
    _write_local_mirror(_BACKEND_ROOT, out_dir, final_snap, meta)
    _save(out_dir, "18_final_enriched_snapshot", final_snap)

    hints = _analyze_artifacts(out_dir)
    _save(out_dir, "_analysis_hints", hints)
    log("--- analysis hints ---")
    for k, v in hints.items():
        log(f"  {k}: {v}")

    quality = evaluate_quality(final_snap, hands_on_effective=hands_on_effective, stress=args.stress)
    quality["hints"] = hints
    log("--- quality gates ---")
    log(json.dumps(quality, indent=2, default=str))

    if not args.preserve_guardrail and prev_guard is not None:
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

    _write_enrichment_quality_report(_BACKEND_ROOT, out_dir, final_snap, quality, meta)
    _write_summary(out_dir, lines, meta, quality)

    if not quality.get("passed"):
        if args.quality_warnings_only:
            log("WARN: quality failures (warnings-only mode — exit 0)")
            log(f"Done. Artifacts: {out_dir}")
            return 0
        log(f"QUALITY FAIL: {quality.get('failures')}")
        return 4

    log(f"Done. Artifacts: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

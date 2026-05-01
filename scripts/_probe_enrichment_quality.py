"""
End-to-end quality probe for contact.enrichment_v1 with the in-house DuckDuckGo search.

Runs a mix of contact archetypes concurrently:
  - Famous public figures (easy enrichment — many sources expected)
  - Common real estate professional archetypes (realistic CRM personas)
  - A contact with only a name (no email)
  - A well-known local real estate broker name

For each result, prints:
  - Search query used
  - DuckDuckGo backend confirmed
  - Pages scraped / relevance-kept
  - sources_count from web research LLM
  - synthesis suggested_note (first 300 chars)
  - tags produced
  - Quality verdict

Saves full JSON to test_outputs/enrichment_quality_{timestamp}.json
"""
from __future__ import annotations

import base64
import json
import os
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

_SCRIPTS = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_SCRIPTS)
_WORKSPACE = os.path.dirname(_BACKEND)
sys.path.insert(0, _WORKSPACE)

from backend.cli.client import request as cli_request
from backend.cli.config import get_token

# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_uid() -> str:
    token = get_token()
    parts = token.split(".")
    if len(parts) >= 2:
        padded = parts[1] + "=" * (4 - len(parts[1]) % 4)
        claims = json.loads(base64.urlsafe_b64decode(padded))
        return str(claims.get("user_id") or claims.get("sub") or "")
    return ""


def _run_enrichment(uid: str, contact: dict) -> dict:
    """Invoke contact.enrichment_v1 for a single contact; return full result dict."""
    run_id = uuid.uuid4().hex[:8]
    fake_fub_id = int(run_id, 16) % 999_999 + 100_000

    first = contact.get("first", "")
    last  = contact.get("last", "")
    email = contact.get("email", "")
    label = contact.get("label", f"{first} {last}".strip())

    fub_person: dict = {
        "firstName": first,
        "lastName": last,
        "id": fake_fub_id,
    }
    if email:
        # Use the original email unchanged — the unique fake_fub_id already ensures
        # a different internal-client doc-id each run so the duplicate-check never halts.
        fub_person["emails"] = [{"value": email}]

    state = {
        "state_version": 1,
        "correlation_id": f"quality_probe_{run_id}",
        "source": {"provider": "followupboss", "event_type": "personCreated"},
        "user_id": uid,
        "payload": {"fubPerson": fub_person},
        "metadata": {"execution_policy": {"volatile_external_allowed": False}},
    }

    t0 = time.perf_counter()
    try:
        st, body = cli_request(
            "POST",
            "/core/v1/run",
            json={"workflow_id": "contact.enrichment_v1", "state": state},
            timeout=90,
        )
        elapsed = time.perf_counter() - t0
    except Exception as exc:
        return {
            "label": label,
            "error": str(exc),
            "elapsed": time.perf_counter() - t0,
            "http": 599,
        }

    resp   = body if isinstance(body, dict) else {}
    resp_state = resp.get("state") or {}
    meta   = resp_state.get("metadata") or {}
    ce     = meta.get("contactEnrichment") or {}
    synth  = ce.get("synthesis") or {}
    wr     = ce.get("webResearch") or {}
    pipe   = wr.get("pipeline") or {}

    # Pull synthesis result (note + tags)
    synth_updates = synth.get("updates") or {}
    suggested_note = synth_updates.get("suggested_note") or synth.get("suggested_note") or ""
    tags           = synth_updates.get("tags") or synth.get("tags") or []

    return {
        "label":          label,
        "http":           st,
        "elapsed":        round(elapsed, 1),
        "wf_status":      resp.get("status"),
        "query":          wr.get("query"),
        "search_backend": pipe.get("search_backend"),
        "scrape_ok":      pipe.get("scrape_ok"),
        "rel_kept":       pipe.get("relevance_kept"),
        "rel_rejected":   pipe.get("relevance_rejected"),
        "rej_reasons":    pipe.get("rejection_reasons"),
        "sources_count":  wr.get("sources_count"),
        "wr_mode":        wr.get("mode"),
        "suggested_note": suggested_note,
        "tags":           tags,
        "raw_state":      resp_state,   # full state for deep analysis
    }


# ── Test contacts ─────────────────────────────────────────────────────────────
# Mix of: famous public figures, realistic CRM archetypes, edge cases.

CONTACTS = [
    # Famous public figures — web search should find many rich sources
    {"label": "Warren Buffett (famous investor)",
     "first": "Warren", "last": "Buffett",
     "email": "warren@berkshire.com"},
    {"label": "Barbara Corcoran (RE celeb)",
     "first": "Barbara", "last": "Corcoran",
     "email": "barbara@corcoran.com"},
    {"label": "Ryan Serhant (broker/TV)",
     "first": "Ryan", "last": "Serhant",
     "email": "ryan@serhant.com"},

    # Realistic CRM contact archetypes
    {"label": "John Smith (generic buyer)",
     "first": "John", "last": "Smith",
     "email": "jsmith@company.com"},
    {"label": "Sarah Johnson (local broker)",
     "first": "Sarah", "last": "Johnson",
     "email": "sarah.johnson@realty.com"},
    {"label": "Mike Chen (tech investor)",
     "first": "Mike", "last": "Chen",
     "email": "mchen@ventures.io"},

    # Edge cases
    {"label": "Name-only (no email)",
     "first": "David", "last": "Williams"},
    {"label": "Single name only",
     "first": "Madonna", "last": "",
     "email": ""},
]


# ── Runner ────────────────────────────────────────────────────────────────────

def main() -> None:
    uid = _get_uid()
    if not uid:
        print("ERROR: Could not get UID — run `acs auth login` first.")
        sys.exit(1)

    print("=" * 70)
    print(f"  contact.enrichment_v1 Quality Probe  •  {len(CONTACTS)} contacts")
    print(f"  uid={uid[:12]}...  {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")
    print("=" * 70)

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {pool.submit(_run_enrichment, uid, c): c for c in CONTACTS}
        completed = 0
        for fut in as_completed(futs):
            r = fut.result()
            results.append(r)
            completed += 1
            _print_result(r, completed, len(CONTACTS))

    # Save full JSON
    os.makedirs(os.path.join(_SCRIPTS, "test_outputs"), exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = os.path.join(_SCRIPTS, "test_outputs", f"enrichment_quality_{ts}.json")
    with open(out_path, "w") as f:
        json.dump({"timestamp": ts, "uid": uid, "results": results}, f, indent=2)

    print()
    print("=" * 70)
    _print_summary(results)
    print(f"\n  Full output saved → {out_path}")
    print("=" * 70)


def _print_result(r: dict, n: int, total: int) -> None:
    print()
    print(f"  [{n}/{total}] {r['label']}")
    print(f"    http={r.get('http')}  elapsed={r.get('elapsed')}s  status={r.get('wf_status')}")
    if r.get("error"):
        print(f"    ERROR: {r['error']}")
        return
    print(f"    query         : {(r.get('query') or '')[:80]}")
    print(f"    backend       : {r.get('search_backend')}  scrape_ok={r.get('scrape_ok')}  "
          f"rel_kept={r.get('rel_kept')}  sources={r.get('sources_count')}")
    print(f"    wr_mode       : {r.get('wr_mode')}")
    note = (r.get("suggested_note") or "").strip()
    note_preview = note[:200].replace("\n", " ")
    print(f"    note          : {note_preview or '(none)'}")
    tags = r.get("tags") or []
    print(f"    tags          : {tags[:8]}")
    verdict = _verdict(r)
    print(f"    verdict       : {verdict}")


def _verdict(r: dict) -> str:
    if r.get("error"):
        return "✗ error"
    if r.get("http", 0) >= 400:
        return f"✗ HTTP {r.get('http')}"
    sc = r.get("sources_count") or 0
    note = (r.get("suggested_note") or "").strip()
    backend = r.get("search_backend") or "none"
    scrape = r.get("scrape_ok") or 0
    if backend == "duckduckgo" and scrape > 0 and sc > 0 and note:
        return "✓ PASS — DDG + sources + note"
    if backend == "duckduckgo" and scrape > 0 and note:
        return "~ PARTIAL — DDG scraped, note present but 0 sources"
    if note:
        return "~ PARTIAL — note present, no web sources"
    return "✗ FAIL — no note generated"


def _print_summary(results: list[dict]) -> None:
    passed   = sum(1 for r in results if "✓" in _verdict(r))
    partial  = sum(1 for r in results if "~" in _verdict(r))
    failed   = sum(1 for r in results if "✗" in _verdict(r))
    avg_src  = sum(r.get("sources_count") or 0 for r in results) / max(len(results), 1)
    with_note = sum(1 for r in results if (r.get("suggested_note") or "").strip())
    ddg_ok   = sum(1 for r in results if r.get("search_backend") == "duckduckgo" and (r.get("scrape_ok") or 0) > 0)

    print(f"  PASS={passed}  PARTIAL={partial}  FAIL={failed}  "
          f"(of {len(results)})")
    print(f"  avg sources_count : {avg_src:.1f}")
    print(f"  notes generated   : {with_note}/{len(results)}")
    print(f"  DDG scraping OK   : {ddg_ok}/{len(results)}")


if __name__ == "__main__":
    main()

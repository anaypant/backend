"""
Concurrent regression & quality test suite for lead.scoring_v1 and contact.enrichment_v1.

Runs all test cases in parallel and prints a structured report with pass/fail assertions.
"""

import sys, time, json, textwrap
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, "C:/Users/anayp/Documents/acs")
from backend.cli.client import request

UID = "d0ihHKrh7xVhpALiVRFOLCzeA0h1"
SEP = "─" * 72

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def run_workflow(workflow_id: str, payload_body: dict, *, source_provider="followupboss", event_type="personUpdated", timeout=120):
    cid = f"cli_{int(time.time() * 1000)}"
    body = {
        "workflow_id": workflow_id,
        "state": {
            "state_version": 1,
            "correlation_id": cid,
            "source": {"provider": source_provider, "event_type": event_type},
            "user_id": UID,
            "payload": payload_body,
            "metadata": {
                "execution_policy": {
                    "volatile_external_allowed": False,
                    "integration_maintenance_allowed": True,
                }
            },
        },
    }
    t0 = time.time()
    status, resp = request("POST", "/core/v1/run", json=body, timeout=timeout)
    elapsed = round(time.time() - t0, 2)
    return status, resp, elapsed


def extract_scoring(resp: dict) -> dict:
    meta = resp.get("state", {}).get("metadata", {})
    return {
        "audit": meta.get("workflowAudit", {}),
        "scoring": meta.get("leadScoring", {}),
        "errors": resp.get("state", {}).get("errors") or [],
    }


def extract_enrichment(resp: dict) -> dict:
    meta = resp.get("state", {}).get("metadata", {})
    return {
        "audit": meta.get("workflowAudit", {}),
        "enrichment": meta.get("contactEnrichment", {}),
        "errors": resp.get("state", {}).get("errors") or [],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Test definitions
# ─────────────────────────────────────────────────────────────────────────────

TESTS = [

    # ── SCORING: High-value buyer — expect hot (score >= 70) ──────────────────
    {
        "id": "S1",
        "label": "Hot buyer — Elon Musk (cash, 100ac Austin, responded in 2hr)",
        "workflow": "lead.scoring_v1",
        "payload": {
            "person": {
                "id": 9001,
                "firstName": "Elon", "lastName": "Musk",
                "emails": [{"value": "elon@x.com"}],
                "phones": [{"value": "+1-512-555-0001"}],
                "stage": "Active Buyer",
                "source": "Referral",
                "price": 50000000,
                "tags": ["ultra-high-net-worth", "cash-buyer", "compound-buyer"],
                "lastContacted": "2026-04-30T00:00:00Z",
                "notes": [
                    "Responded to outreach within 2 hours. Budget unconstrained.",
                    "Wants 100+ acres Travis County, private airstrip access, gated. No HOA.",
                    "Cash buyer, can close in 30 days. Follow-up call confirmed.",
                ],
            }
        },
        "assertions": [
            ("final_score >= 70", lambda r: r["scoring"].get("final", {}).get("score", 0) >= 70),
            ("is_hot == True",    lambda r: r["scoring"].get("final", {}).get("is_hot") is True),
            ("det_score >= 40",   lambda r: r["scoring"].get("deterministic", {}).get("score", 0) >= 40),
            ("llm_score >= 25",   lambda r: r["scoring"].get("llm", {}).get("score", 0) >= 25),
            ("rationale present", lambda r: len(r["scoring"].get("llm", {}).get("rationale", "")) > 20),
        ],
    },

    # ── SCORING: Zillow paid lead, moderate engagement ─────────────────────────
    {
        "id": "S2",
        "label": "Paid Zillow lead — Sarah Chen (new inquiry, moderate signals)",
        "workflow": "lead.scoring_v1",
        "payload": {
            "person": {
                "id": 9002,
                "firstName": "Sarah", "lastName": "Chen",
                "emails": [{"value": "sarah.chen@gmail.com"}],
                "phones": [{"value": "+1-415-555-0202"}],
                "stage": "New Lead",
                "source": "Zillow",
                "price": 1200000,
                "tags": [],
                "lastContacted": "2026-04-28T12:00:00Z",
                "notes": [
                    "Inquired on 3/2 Westlake listing. Looking for 4bd 3ba under $1.3M.",
                    "Has pre-approval letter from Chase, $1.25M limit.",
                ],
            }
        },
        "assertions": [
            ("final_score > 20",      lambda r: r["scoring"].get("final", {}).get("score", 0) > 20),
            ("paid_source scored",    lambda r: any("paid_source" in x for x in r["scoring"].get("deterministic", {}).get("reasons", []))),
            ("rationale present",     lambda r: len(r["scoring"].get("llm", {}).get("rationale", "")) > 20),
        ],
    },

    # ── SCORING: Motivated seller — expect mid-high score ─────────────────────
    {
        "id": "S3",
        "label": "Motivated seller — Marcus Johnson (divorce, must sell 60 days)",
        "workflow": "lead.scoring_v1",
        "payload": {
            "person": {
                "id": 9003,
                "firstName": "Marcus", "lastName": "Johnson",
                "emails": [{"value": "marcus.j@outlook.com"}],
                "phones": [{"value": "+1-305-555-0303"}],
                "stage": "Active Seller",
                "source": "Referral",
                "price": 875000,
                "tags": ["motivated-seller", "divorce"],
                "lastContacted": "2026-04-29T09:00:00Z",
                "notes": [
                    "Going through divorce. Must sell within 60 days, attorney involved.",
                    "Property at 4412 Coral Way Miami. Willing to price below market for fast close.",
                    "Very responsive — texted back same day.",
                ],
            }
        },
        "assertions": [
            ("final_score >= 50", lambda r: r["scoring"].get("final", {}).get("score", 0) >= 50),
            ("stage:active_seller scored", lambda r: any("active seller" in x for x in r["scoring"].get("deterministic", {}).get("reasons", []))),
        ],
    },

    # ── SCORING: Cold/dead lead — expect low score ────────────────────────────
    {
        "id": "S4",
        "label": "Dead lead — Bob Williams (inactive 6mo, no contact info)",
        "workflow": "lead.scoring_v1",
        "payload": {
            "person": {
                "id": 9004,
                "firstName": "Bob", "lastName": "Williams",
                "emails": [],
                "phones": [],
                "stage": "Inactive",
                "source": "Cold Outreach",
                "tags": ["cold", "no-response"],
                "lastContacted": "2025-09-01T00:00:00Z",
                "notes": ["Never responded to any follow-up. 6 months stale."],
            }
        },
        "assertions": [
            ("final_score < 35",       lambda r: r["scoring"].get("final", {}).get("score", 0) < 35),
            ("is_hot == False",        lambda r: r["scoring"].get("final", {}).get("is_hot") is False),
            ("inactive penalty applied", lambda r: any("inactive" in x for x in r["scoring"].get("deterministic", {}).get("reasons", []))),
        ],
    },

    # ── SCORING: Sparse contact — just a name, no other data ─────────────────
    {
        "id": "S5",
        "label": "Sparse lead — Jane Doe (name only, no contact or context)",
        "workflow": "lead.scoring_v1",
        "payload": {
            "person": {
                "id": 9005,
                "firstName": "Jane", "lastName": "Doe",
            }
        },
        "assertions": [
            ("completes without error",  lambda r: len(r["errors"]) == 0),
            ("final_score >= 0",         lambda r: r["scoring"].get("final", {}).get("score", 0) >= 0),
            ("score <= 30",              lambda r: r["scoring"].get("final", {}).get("score", 0) <= 30),
        ],
    },

    # ── SCORING: Under contract — should score well (high intent confirmed) ───
    {
        "id": "S6",
        "label": "Under contract — Priya Patel (offer accepted, closing in 3wk)",
        "workflow": "lead.scoring_v1",
        "payload": {
            "person": {
                "id": 9006,
                "firstName": "Priya", "lastName": "Patel",
                "emails": [{"value": "priya.patel@gmail.com"}],
                "phones": [{"value": "+1-408-555-0606"}],
                "stage": "Contract",
                "source": "Organic",
                "price": 2400000,
                "tags": ["first-time-buyer", "tech-exec"],
                "lastContacted": "2026-04-29T15:00:00Z",
                "notes": [
                    "Offer accepted on 512 Oak Knoll Dr, Atherton. Closing in 3 weeks.",
                    "Financing through SVB Private. No contingencies remaining.",
                ],
            }
        },
        "assertions": [
            ("final_score >= 40", lambda r: r["scoring"].get("final", {}).get("score", 0) >= 40),
            ("stage:contract scored", lambda r: any("contract" in x for x in r["scoring"].get("deterministic", {}).get("reasons", []))),
        ],
    },

    # ── SCORING: Real synced FUB lead (followupboss_101) — canonical ID fix ──
    {
        "id": "S7",
        "label": "Synced FUB lead — followupboss_101 (canonical ID mismatch fix)",
        "workflow": "lead.scoring_v1",
        "payload": {"person": {"id": 101}},
        "assertions": [
            ("completes without error",  lambda r: len(r["errors"]) == 0),
            ("canonical ID is fub_101",  lambda r: "followupboss_101" in (r["audit"].get("nodes") or [{}])[1].get("extra", {}).get("canonical_id", "")),
        ],
    },

    # ── ENRICHMENT: Named person — should extract display_name + build good query ──
    {
        "id": "E1",
        "label": "Enrichment — Oprah Winfrey (named, should normalize + do web research)",
        "workflow": "contact.enrichment_v1",
        "payload": {
            "person": {
                "id": 8001,
                "firstName": "Oprah", "lastName": "Winfrey",
                "emails": [{"value": "oprah@harpo.com"}],
                "phones": [{"value": "+1-310-555-0801"}],
            },
            "event": "personCreated",
            "eventId": f"test_e1_{int(time.time())}",
        },
        "event_type": "personCreated",
        "assertions": [
            ("completes without error", lambda r: len(r["errors"]) == 0),
            ("display_name extracted",  lambda r: "oprah" in str(r["enrichment"].get("normalized", {}).get("display_name", "")).lower()),
            ("web research ran",        lambda r: r["enrichment"].get("webResearch", {}).get("http_status") == 200),
        ],
    },

    # ── ENRICHMENT: Anonymous contact — graceful empty handling ───────────────
    {
        "id": "E2",
        "label": "Enrichment — anonymous contact (no name, just email)",
        "workflow": "contact.enrichment_v1",
        "payload": {
            "person": {
                "id": 8002,
                "emails": [{"value": "buyer2024@yahoo.com"}],
            },
            "event": "personCreated",
            "eventId": f"test_e2_{int(time.time())}",
        },
        "event_type": "personCreated",
        "assertions": [
            ("completes without error", lambda r: len(r["errors"]) == 0),
            ("web research ran",        lambda r: r["enrichment"].get("webResearch", {}).get("http_status") == 200),
        ],
    },

]

# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

def run_test(test: dict):
    t0 = time.time()
    try:
        kwargs = {}
        if "event_type" in test:
            kwargs["event_type"] = test["event_type"]
        status, resp, elapsed = run_workflow(test["workflow"], test["payload"], **kwargs)
    except Exception as exc:
        return test, None, None, 0, str(exc)
    return test, status, resp, elapsed, None


def check_assertions(test: dict, resp: dict) -> list[tuple[str, bool]]:
    wf = test["workflow"]
    if "scoring" in wf:
        data = extract_scoring(resp)
    else:
        data = extract_enrichment(resp)

    results = []
    for label, fn in test.get("assertions", []):
        try:
            passed = fn(data)
        except Exception as e:
            passed = False
        results.append((label, passed))
    return results, data


def format_score_summary(data: dict) -> str:
    sc = data.get("scoring", {})
    det = sc.get("deterministic", {})
    llm = sc.get("llm", {})
    final = sc.get("final", {})
    rationale = (llm.get("rationale") or "")[:200]
    return (
        f"  Score: {det.get('score','?')}/60 det + {llm.get('score','?')}/40 llm = "
        f"{final.get('score','?')}/100  hot={final.get('is_hot')}  "
        f"reasons={det.get('reasons', [])}\n"
        f"  Rationale: {textwrap.fill(rationale, 70, subsequent_indent='             ')}"
    )


def format_enrichment_summary(data: dict) -> str:
    ce = data.get("enrichment", {})
    norm = ce.get("normalized", {})
    syn = ce.get("synthesis", {})
    wr = ce.get("webResearch", {})
    return (
        f"  Normalized: name={norm.get('display_name')!r}  "
        f"emails={norm.get('emails')}  ext_id={norm.get('external_person_id')!r}\n"
        f"  WebResearch: http={wr.get('http_status')}  sources={wr.get('sources')}\n"
        f"  Synthesis: {syn}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    print(f"\n{'━' * 72}")
    print(f"  ACS Workflow Test Suite  ({len(TESTS)} tests, running concurrently)")
    print(f"{'━' * 72}\n")

    results = {}
    wall_start = time.time()

    with ThreadPoolExecutor(max_workers=len(TESTS)) as pool:
        futures = {pool.submit(run_test, t): t for t in TESTS}
        for fut in as_completed(futures):
            test, status, resp, elapsed, err = fut.result()
            results[test["id"]] = (test, status, resp, elapsed, err)
            print(f"  ✓ finished [{test['id']}] in {elapsed}s  — {test['label'][:55]}")

    wall = round(time.time() - wall_start, 2)
    print(f"\n  All done in {wall}s wall time\n")

    # ── Print detailed results in test order ──
    total_assertions = 0
    passed_assertions = 0
    failed_tests = []

    for test in TESTS:
        tid = test["id"]
        t, status, resp, elapsed, err = results[tid]

        print(f"\n{SEP}")
        print(f"[{tid}] {test['label']}")
        print(f"       HTTP {status}  {elapsed}s")

        if err:
            print(f"  ERROR: {err}")
            failed_tests.append(tid)
            continue

        if not resp or resp.get("status") == "failed":
            errs = (resp or {}).get("state", {}).get("errors") or []
            print(f"  WORKFLOW FAILED: {errs}")
            failed_tests.append(tid)

        assertion_results, data = check_assertions(test, resp)

        # Summary line
        if "scoring" in test["workflow"]:
            print(format_score_summary(data))
        else:
            print(format_enrichment_summary(data))

        # Assertions
        print()
        for a_label, passed in assertion_results:
            mark = "  ✅" if passed else "  ❌"
            print(f"{mark}  {a_label}")
            total_assertions += 1
            if passed:
                passed_assertions += 1
            else:
                if tid not in failed_tests:
                    failed_tests.append(tid)

    # ── Final summary ──
    print(f"\n{'━' * 72}")
    print(f"  RESULTS: {passed_assertions}/{total_assertions} assertions passed")
    if failed_tests:
        print(f"  FAILED tests: {', '.join(failed_tests)}")
    else:
        print("  ALL TESTS PASSED ✅")
    print(f"  Wall time: {wall}s")
    print(f"{'━' * 72}\n")


if __name__ == "__main__":
    main()

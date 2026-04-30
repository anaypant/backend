"""
ACS End-to-End Test Suite
=========================
Phase 1  — Concurrent workflow regression (lead.scoring_v1 + contact.enrichment_v1)
Phase 2  — Sequential FUB integration (create → tag → note → score → read-back from Firestore)

FUB Phase 2 requires the new gateway routes to be deployed (terraform apply on backend/api/).
If the gateway hasn't been updated yet, Phase 2 prints a clear skip notice and exits cleanly.
"""

import sys, time, json, textwrap
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, "C:/Users/anayp/Documents/acs")
from backend.cli.client import request

UID  = "d0ihHKrh7xVhpALiVRFOLCzeA0h1"
SEP  = "─" * 72
BOLD = "━" * 72

# ─────────────────────────────────────────────────────────────────────────────
# Workflow helpers
# ─────────────────────────────────────────────────────────────────────────────

def run_workflow(workflow_id: str, payload_body: dict, *, source_provider="followupboss",
                 event_type="personUpdated", timeout=120):
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
    return status, resp, round(time.time() - t0, 2)


def extract_scoring(resp: dict) -> dict:
    meta = resp.get("state", {}).get("metadata", {})
    return {
        "audit":   meta.get("workflowAudit", {}),
        "scoring": meta.get("leadScoring", {}),
        "errors":  resp.get("state", {}).get("errors") or [],
    }


def extract_enrichment(resp: dict) -> dict:
    meta = resp.get("state", {}).get("metadata", {})
    return {
        "audit":      meta.get("workflowAudit", {}),
        "enrichment": meta.get("contactEnrichment", {}),
        "errors":     resp.get("state", {}).get("errors") or [],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1 — Workflow test definitions
# ─────────────────────────────────────────────────────────────────────────────

TESTS = [

    # ── SCORING: High-value buyer — expect hot (score >= 70) ─────────────────
    {
        "id": "S1",
        "label": "Hot buyer — Elon Musk (cash, 100ac Austin, responded 2hr)",
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
                    "Wants 100+ acres Travis County, private airstrip access. Cash buyer.",
                    "Can close in 30 days. Follow-up call confirmed.",
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

    # ── SCORING: Zillow paid lead, moderate engagement ────────────────────────
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
            ("final_score > 20",   lambda r: r["scoring"].get("final", {}).get("score", 0) > 20),
            ("paid_source scored", lambda r: any("paid_source" in x for x in r["scoring"].get("deterministic", {}).get("reasons", []))),
            ("rationale present",  lambda r: len(r["scoring"].get("llm", {}).get("rationale", "")) > 20),
        ],
    },

    # ── SCORING: Motivated seller — expect mid-high score ────────────────────
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
                    "Property at 4412 Coral Way Miami. Below-market for fast close.",
                    "Very responsive — texted back same day.",
                ],
            }
        },
        "assertions": [
            ("final_score >= 50",            lambda r: r["scoring"].get("final", {}).get("score", 0) >= 50),
            ("stage:active_seller scored",   lambda r: any("active seller" in x for x in r["scoring"].get("deterministic", {}).get("reasons", []))),
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
            ("final_score < 35",          lambda r: r["scoring"].get("final", {}).get("score", 0) < 35),
            ("is_hot == False",           lambda r: r["scoring"].get("final", {}).get("is_hot") is False),
            ("inactive penalty applied",  lambda r: any("inactive" in x for x in r["scoring"].get("deterministic", {}).get("reasons", []))),
        ],
    },

    # ── SCORING: Sparse contact — name only ──────────────────────────────────
    {
        "id": "S5",
        "label": "Sparse lead — Jane Doe (name only, no contact or context)",
        "workflow": "lead.scoring_v1",
        "payload": {"person": {"id": 9005, "firstName": "Jane", "lastName": "Doe"}},
        "assertions": [
            ("completes without error", lambda r: len(r["errors"]) == 0),
            ("final_score >= 0",        lambda r: r["scoring"].get("final", {}).get("score", 0) >= 0),
            ("score <= 30",             lambda r: r["scoring"].get("final", {}).get("score", 0) <= 30),
        ],
    },

    # ── SCORING: Under contract — high intent confirmed ───────────────────────
    {
        "id": "S6",
        "label": "Under contract — Priya Patel (offer accepted, closing 3wk)",
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
            ("final_score >= 40",     lambda r: r["scoring"].get("final", {}).get("score", 0) >= 40),
            ("stage:contract scored", lambda r: any("contract" in x for x in r["scoring"].get("deterministic", {}).get("reasons", []))),
        ],
    },

    # ── SCORING: Real synced FUB lead (canonical ID fix) ─────────────────────
    {
        "id": "S7",
        "label": "Synced FUB lead — followupboss_101 (canonical ID fix)",
        "workflow": "lead.scoring_v1",
        "payload": {"person": {"id": 101}},
        "assertions": [
            ("completes without error", lambda r: len(r["errors"]) == 0),
            ("canonical ID correct",    lambda r: "followupboss_101" in (
                (r["audit"].get("nodes") or [{}])[1].get("extra", {}).get("canonical_id", "")
                if len(r["audit"].get("nodes") or []) > 1 else ""
            )),
        ],
    },

    # ── ENRICHMENT: Named person ──────────────────────────────────────────────
    {
        "id": "E1",
        "label": "Enrichment — Oprah Winfrey (normalize + web research)",
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

    # ── ENRICHMENT: Anonymous contact ─────────────────────────────────────────
    {
        "id": "E2",
        "label": "Enrichment — anonymous (no name, just email)",
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
# Phase 1 — Runner helpers
# ─────────────────────────────────────────────────────────────────────────────

def run_test(test: dict):
    try:
        kwargs = {}
        if "event_type" in test:
            kwargs["event_type"] = test["event_type"]
        status, resp, elapsed = run_workflow(test["workflow"], test["payload"], **kwargs)
    except Exception as exc:
        return test, None, None, 0, str(exc)
    return test, status, resp, elapsed, None


def check_assertions(test: dict, resp: dict):
    wf   = test["workflow"]
    data = extract_scoring(resp) if "scoring" in wf else extract_enrichment(resp)
    results = []
    for label, fn in test.get("assertions", []):
        try:
            passed = fn(data)
        except Exception:
            passed = False
        results.append((label, passed))
    return results, data


def fmt_score(data: dict) -> str:
    sc    = data.get("scoring", {})
    det   = sc.get("deterministic", {})
    llm   = sc.get("llm", {})
    final = sc.get("final", {})
    rat   = (llm.get("rationale") or "")[:200]
    return (
        f"  Score: {det.get('score','?')}/60 det + {llm.get('score','?')}/40 llm = "
        f"{final.get('score','?')}/100  hot={final.get('is_hot')}  "
        f"reasons={det.get('reasons', [])}\n"
        f"  Rationale: {textwrap.fill(rat, 70, subsequent_indent='             ')}"
    )


def fmt_enrichment(data: dict) -> str:
    ce   = data.get("enrichment", {})
    norm = ce.get("normalized", {})
    syn  = ce.get("synthesis", {})
    wr   = ce.get("webResearch", {})
    return (
        f"  Normalized: name={norm.get('display_name')!r}  "
        f"emails={norm.get('emails')}  ext_id={norm.get('external_person_id')!r}\n"
        f"  WebResearch: http={wr.get('http_status')}  sources={wr.get('sources')}\n"
        f"  Synthesis: {syn}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 — FUB end-to-end helpers
# ─────────────────────────────────────────────────────────────────────────────

_FUB_TEST_TAG = "acs-e2e-test"
_FUB_TEST_EMAIL = f"acs.e2e.{int(time.time())}@test.invalid"


def fub(path: str, body: dict | None = None, method: str = "POST") -> tuple[int, dict]:
    return request(method, f"/integrations/followupboss{path}", json=body or {})


def _check_gateway_deployed() -> bool:
    """Probe a new FUB route to confirm the gateway has been updated."""
    st, _ = fub("/people/list", {"limit": 1})
    return st != 404


def _print_step(label: str, ok: bool, detail: str = ""):
    mark = "  ✅" if ok else "  ❌"
    line = f"{mark}  {label}"
    if detail:
        line += f"  — {detail}"
    print(line)


def run_fub_e2e() -> tuple[int, int]:
    """
    Sequential FUB integration tests.

    Flow:
      F1  Check FUB connection status (integrated: true)
      F2  Create a test person in FUB
      F3  Read person back — verify name + email
      F4  Add tags (acs-e2e-test, high-value-lead)
      F5  Add a note
      F6  Trigger lead.scoring_v1 on the new FUB person ID
      F7  Trigger contact.enrichment_v1 on the new FUB person ID
      F8  Read person back from FUB — verify tags still present
      F9  Confirm ACS Firestore has lead data for the canonical ID
      F10 Clean up — remove test tag (idempotent)

    Returns (passed, total) assertion counts.
    """
    passed = total = 0

    def assert_step(label: str, condition: bool, detail: str = "") -> bool:
        nonlocal passed, total
        total += 1
        _print_step(label, condition, detail)
        if condition:
            passed += 1
        return condition

    print(f"\n{SEP}")
    print("[Phase 2]  FUB End-to-End Integration")
    print(SEP)

    # ── F1: Check FUB status ─────────────────────────────────────────────────
    print("\n  F1 — FUB connection status")
    st, body = fub("/status", method="GET")
    integrated = body.get("integrated") is True
    assert_step("integrated == True", integrated, f"status={body.get('connectionStatus')}")
    if not integrated:
        print("  SKIP: FUB not integrated. Complete OAuth at /integrations/followupboss/oauth/start")
        return passed, total

    # ── F2: Create test person ────────────────────────────────────────────────
    print("\n  F2 — Create test person in FUB")
    st, body = fub("/people/create", {
        "firstName": "ACS",
        "lastName":  "E2ETest",
        "emails":    [{"value": _FUB_TEST_EMAIL}],
        "phones":    [{"value": "+15125550199"}],
        "tags":      [_FUB_TEST_TAG],
        "source":    "ACS CLI",
        "stage":     "New Lead",
        "price":     750000,
    })
    person_id = (body.get("person") or body.get("people", [{}]) or [{}])[0].get("id") if st in (200, 201) else None
    if person_id is None and isinstance(body.get("id"), int):
        person_id = body["id"]
    ok_create = st in (200, 201) and person_id is not None
    assert_step("Person created", ok_create, f"HTTP {st}  person_id={person_id}")
    if not ok_create:
        print(f"  Response: {json.dumps(body, indent=4)}")
        print("  SKIP: Cannot proceed without a person_id.")
        return passed, total

    print(f"  Person ID: {person_id}")
    time.sleep(1)  # allow FUB to index the new record

    # ── F3: Read person back ──────────────────────────────────────────────────
    print("\n  F3 — Read person back from FUB")
    st, body = fub("/people/get", {"personId": person_id})
    person = body.get("person") or body
    got_name  = f"{person.get('firstName','')} {person.get('lastName','')}".strip()
    got_email = next((e.get("value","") for e in (person.get("emails") or [])), "")
    assert_step("name == 'ACS E2ETest'",    got_name  == "ACS E2ETest",   f"got {got_name!r}")
    assert_step("email matches",            _FUB_TEST_EMAIL in got_email, f"got {got_email!r}")

    # ── F4: Add tags ──────────────────────────────────────────────────────────
    print("\n  F4 — Add tags to person")
    st, body = fub("/people/tags/add", {"personId": person_id, "tags": ["high-value-lead", "acs-scored"]})
    assert_step("Tags added (HTTP 2xx)", st in (200, 201), f"HTTP {st}  {body.get('message') or ''}")

    # ── F5: Add note ──────────────────────────────────────────────────────────
    print("\n  F5 — Add note to person")
    st, body = fub("/notes/create", {
        "personId": person_id,
        "body":     f"ACS E2E test note — created at {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
    })
    assert_step("Note created (HTTP 2xx)", st in (200, 201), f"HTTP {st}")

    # ── F6: Lead scoring on the new FUB person ────────────────────────────────
    print("\n  F6 — Run lead.scoring_v1 on new FUB person")
    scoring_status, scoring_resp, scoring_elapsed = run_workflow(
        "lead.scoring_v1",
        {"person": {"id": person_id}},
    )
    sc_data = extract_scoring(scoring_resp)
    final   = sc_data["scoring"].get("final", {})
    assert_step("Scoring completes (HTTP 200)",  scoring_status == 200,       f"{scoring_elapsed}s")
    assert_step("No workflow errors",            len(sc_data["errors"]) == 0, f"errors={sc_data['errors']}")
    assert_step("Score returned (>= 0)",         final.get("score", -1) >= 0, f"score={final.get('score')}")
    print(f"  {fmt_score(sc_data)}")

    # ── F7: Contact enrichment on the new FUB person ──────────────────────────
    print("\n  F7 — Run contact.enrichment_v1 on new FUB person")
    enrich_status, enrich_resp, enrich_elapsed = run_workflow(
        "contact.enrichment_v1",
        {
            "person": {"id": person_id},
            "event":   "personCreated",
            "eventId": f"e2e_f7_{person_id}",
        },
        event_type="personCreated",
    )
    en_data = extract_enrichment(enrich_resp)
    assert_step("Enrichment completes (HTTP 200)", enrich_status == 200,       f"{enrich_elapsed}s")
    assert_step("No enrichment errors",            len(en_data["errors"]) == 0, f"errors={en_data['errors']}")
    print(f"  {fmt_enrichment(en_data)}")

    # ── F8: Read person back from FUB — tags still present ────────────────────
    print("\n  F8 — Verify FUB person after workflows")
    st, body = fub("/people/get", {"personId": person_id})
    person = body.get("person") or body
    all_tags = [t.get("name","").lower() if isinstance(t, dict) else str(t).lower()
                for t in (person.get("tags") or [])]
    has_orig_tag  = _FUB_TEST_TAG in all_tags
    has_score_tag = "acs-scored" in all_tags
    assert_step(f"Original tag '{_FUB_TEST_TAG}' still present", has_orig_tag,  f"tags={all_tags}")
    assert_step("Added 'acs-scored' tag present",                 has_score_tag, f"tags={all_tags}")

    # ── F9: Verify Firestore has lead data ────────────────────────────────────
    print("\n  F9 — Verify ACS Firestore has lead record for canonical ID")
    canonical_id = f"followupboss_{person_id}"
    fs_st, fs_body = request("POST", "/db/read", json={"path": f"Leads/{canonical_id}"})
    lead_data = fs_body.get("data") or {}
    has_score = "leadScore" in lead_data or "score" in lead_data or "leadScoring" in str(lead_data)
    assert_step("Firestore lead record exists",  fs_st == 200,  f"HTTP {fs_st}  path=Leads/{canonical_id}")
    assert_step("Firestore has scoring data",    has_score,     f"keys={list(lead_data.keys())[:8]}")

    # ── F10: Cleanup — remove test tag ────────────────────────────────────────
    print("\n  F10 — Cleanup: remove test tags")
    st, body = fub("/people/tags/remove", {"personId": person_id, "tags": [_FUB_TEST_TAG, "high-value-lead", "acs-scored"]})
    assert_step("Tags removed (HTTP 2xx)", st in (200, 201), f"HTTP {st}")

    return passed, total


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    # ══════════════════════════════════════════════════════════════
    # Phase 1 — Workflow regression (concurrent)
    # ══════════════════════════════════════════════════════════════
    print(f"\n{BOLD}")
    print(f"  Phase 1 — Workflow Regression  ({len(TESTS)} tests, concurrent)")
    print(f"{BOLD}\n")

    results    = {}
    wall_start = time.time()

    with ThreadPoolExecutor(max_workers=len(TESTS)) as pool:
        futures = {pool.submit(run_test, t): t for t in TESTS}
        for fut in as_completed(futures):
            test, status, resp, elapsed, err = fut.result()
            results[test["id"]] = (test, status, resp, elapsed, err)
            print(f"  + finished [{test['id']}] in {elapsed}s  — {test['label'][:55]}")

    wall = round(time.time() - wall_start, 2)
    print(f"\n  All concurrent tests done in {wall}s\n")

    total_assertions  = 0
    passed_assertions = 0
    failed_tests      = []

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

        if "scoring" in test["workflow"]:
            print(fmt_score(data))
        else:
            print(fmt_enrichment(data))

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

    # Phase 1 summary
    print(f"\n{BOLD}")
    print(f"  Phase 1 Results: {passed_assertions}/{total_assertions} assertions passed  "
          f"({wall}s wall)")
    if failed_tests:
        print(f"  FAILED tests: {', '.join(failed_tests)}")
    else:
        print("  ALL WORKFLOW TESTS PASSED")
    print(BOLD)

    # ══════════════════════════════════════════════════════════════
    # Phase 2 — FUB end-to-end (sequential)
    # ══════════════════════════════════════════════════════════════
    print(f"\n{BOLD}")
    print("  Phase 2 — FUB End-to-End Integration")
    print(BOLD)

    # Probe whether the new gateway routes are live (single probe, reuse result)
    gateway_deployed = _check_gateway_deployed()
    fub_passed = fub_total = 0

    if not gateway_deployed:
        print("""
  SKIP — New FUB gateway routes are not deployed yet.

  The gateway.tf has been updated with 10 new routes but requires a Terraform
  apply to take effect.  To deploy:

    cd backend/api
    terraform init
    terraform apply

  Once deployed, re-run this script to see the full end-to-end results.
""")
    else:
        fub_passed, fub_total = run_fub_e2e()
        print(f"\n{BOLD}")
        print(f"  Phase 2 Results: {fub_passed}/{fub_total} assertions passed")
        if fub_passed < fub_total:
            print("  Some FUB assertions failed — check output above.")
        else:
            print("  ALL FUB E2E TESTS PASSED")
        print(BOLD)

    # ── Grand total ──
    fub_suffix = f" + FUB {fub_passed}/{fub_total})" if gateway_deployed else " + FUB SKIPPED)"
    print(f"\n  GRAND TOTAL: {passed_assertions + fub_passed}/{total_assertions + fub_total}  "
          f"(workflow {passed_assertions}/{total_assertions}{fub_suffix}")


if __name__ == "__main__":
    main()

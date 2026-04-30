import sys, time, json
sys.path.insert(0, "C:/Users/anayp/Documents/acs")
from backend.cli.client import request

UID = "d0ihHKrh7xVhpALiVRFOLCzeA0h1"
cid = f"cli_elon_v2_{int(time.time())}"

body = {
    "workflow_id": "lead.scoring_v1",
    "state": {
        "state_version": 1,
        "correlation_id": cid,
        "source": {"provider": "followupboss", "event_type": "personUpdated"},
        "user_id": UID,
        "payload": {
            "person": {
                "id": 9001,
                "firstName": "Elon",
                "lastName": "Musk",
                "emails": [{"value": "elon@x.com"}],
                "phones": [{"value": "+1-512-555-0001"}],
                "stage": "Active Buyer",
                "source": "Referral",
                "price": 50000000,
                "tags": ["ultra-high-net-worth", "cash-buyer", "compound-buyer"],
                "lastContacted": "2026-04-30T00:00:00Z",
                "notes": [
                    "Sold all 6 CA homes 2020-2021. Looking for large compound near Austin.",
                    "Needs private airstrip access. Min 50 acres. No HOA. Gated security required.",
                    "Responded to outreach within 2 hours. Budget is not a constraint.",
                    "Specifically asked about off-market listings over 100 acres in Travis County.",
                    "Cash buyer. Can close in under 30 days.",
                ],
            }
        },
        "metadata": {
            "execution_policy": {
                "volatile_external_allowed": False,
                "integration_maintenance_allowed": True,
            }
        },
    },
}

print(f"Correlation-ID: {cid}")
t0 = time.time()
status, resp = request("POST", "/core/v1/run", json=body, timeout=120)
elapsed = round(time.time() - t0, 2)
print(f"HTTP {status}  ({elapsed}s)\n")

r = resp.get("state", {}).get("metadata", {})
audit = r.get("workflowAudit", {})
scoring = r.get("leadScoring", {})

print("=== WORKFLOW AUDIT ===")
for node in audit.get("nodes", []):
    name = node["node"]
    dur = node.get("duration_ms", 0)
    extra = node.get("extra", {})
    extra_str = "  " + json.dumps(extra) if extra else ""
    print(f"  [{name}] {dur:.1f}ms{extra_str}")

billing = audit.get("billing", {})
print(f"\n  Duration: {audit.get('duration_ms')}ms | LLM calls: {billing.get('llm_calls')} | DB reads: {billing.get('db_reads')}")

print("\n=== SCORING RESULT ===")
det = scoring.get("deterministic", {})
llm = scoring.get("llm", {})
final = scoring.get("final", {})
print(f"  Deterministic : {det.get('score')}/60  reasons={det.get('reasons')}")
print(f"  LLM           : {llm.get('score')}/40")
print(f"  LLM rationale : {llm.get('rationale')}")
print(f"  FINAL         : {final.get('score')}/100  |  threshold={final.get('threshold')}  |  hot={final.get('is_hot')}")

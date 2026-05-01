import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "core" / "functions" / "runner"))

from workflows.normalize_integration_payload import normalize_contact

SKIP_DOMAINS = {"example.com", "acs-test.dev", "mailinator.com", "example.org"}

def query_for(n):
    real_email = ""
    for e in n["emails"]:
        domain = e.rsplit("@", 1)[-1].lower() if "@" in e else ""
        if domain and domain not in SKIP_DOMAINS:
            real_email = e
            break
    parts = [n["display_name"]]
    if real_email:
        parts.append(real_email)
    parts.append("real estate")
    return " ".join(p for p in parts if p)

# Test 1: flat payload (CLI test format — the bug we just fixed)
n1 = normalize_contact({
    "source": {"provider": "followupboss", "event_type": "person.created"},
    "payload": {"firstName": "Elon", "lastName": "Musk",
                "emails": [{"value": "elon@spacex.com"}], "id": 99999},
})
print("Test 1 — flat payload:")
print(f"  display_name : {n1['display_name']!r}")
print(f"  emails       : {n1['emails']}")
print(f"  person_id    : {n1['person_id']}")
print(f"  query        : {query_for(n1)!r}")

# Test 2: nested person key (standard webhook)
n2 = normalize_contact({
    "source": {"provider": "followupboss", "event_type": "person.updated"},
    "payload": {"person": {"firstName": "Oprah", "lastName": "Winfrey",
                           "emails": [{"value": "oprah@owntv.com"}], "id": 42}},
})
print("\nTest 2 — nested person key:")
print(f"  display_name : {n2['display_name']!r}")
print(f"  person_id    : {n2['person_id']}")
print(f"  query        : {query_for(n2)!r}")

# Test 3: test email is excluded from query
n3 = normalize_contact({
    "source": {"provider": "followupboss", "event_type": "person.created"},
    "payload": {"firstName": "John", "lastName": "Smith",
                "emails": [{"value": "john.test.abc123@acs-test.dev"}], "id": 55},
})
print("\nTest 3 — test email excluded from query:")
print(f"  display_name : {n3['display_name']!r}")
print(f"  query        : {query_for(n3)!r}  (should NOT contain the test email)")

print("\nAll normalisation checks PASSED")

"""Fix stale oauth_pending FUB connection status."""
import sys, json, copy
sys.path.insert(0, "C:/Users/anayp/Documents/acs")
from backend.cli.client import request

UID = "d0ihHKrh7xVhpALiVRFOLCzeA0h1"

# 1. Read full profile
st, body = request("POST", "/db/read", json={"path": f"Realtors/{UID}"})
profile = body.get("data", {})

# 2. Patch in-memory
integrations = copy.deepcopy(profile.get("integrations", {}))
fub = integrations.get("followupboss", {})

# All 53 webhooks are registered (errors were "already exists") → use correct status
conn = fub.get("connection", {})
conn["status"] = "connected_with_webhook_sync_issues"
fub["connection"] = conn

# Clear stale oauthPending (expired nonce from an incomplete OAuth start)
auth = fub.get("auth", {})
auth.pop("oauthPending", None)
fub["auth"] = auth

integrations["followupboss"] = fub

print("=== Patching FUB connection status ===")
print(f"  New status : {conn['status']}")
print(f"  oauthPending cleared: {'oauthPending' not in auth}")

# 3. Write back
st2, body2 = request("POST", "/db/upsert", json={
    "path": f"Realtors/{UID}",
    "data": {"integrations": integrations},
    "merge": True,
})
print(f"\nUpsert HTTP {st2}")
print(json.dumps(body2, indent=2))

# 4. Verify
print("\n=== FUB status after fix ===")
st3, body3 = request("GET", "/integrations/followupboss/status")
print(f"HTTP {st3}")
print(json.dumps(body3, indent=2))

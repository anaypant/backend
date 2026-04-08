"""Contract for profile rows at Realtors|Internals/{uid} in Firestore.

Why auth writes here directly (Admin SDK) instead of calling the db service:
- Signup/login already run in auth; bootstrap rows are tightly coupled to identity.
- Calling db through API Gateway would replace the user's Bearer with the gateway SA OIDC
  token, so Firestore rules enforced via verify_id_token in db-upsert would not see the
  end-user JWT unless you bypass the gateway for internal hops or duplicate logic.

How this coexists with the db module:
- db remains the generic /db/* HTTP API for clients (gateways, browsers via proxy).
- Same collection names and field shapes here should be used when clients upsert the
  same paths, or drift will cause confusing bugs.

At larger scale: if profile rules become heavy, prefer a shared Python package imported
by both deployables, or an internal gRPC/Cloud Run call that forwards the user JWT
explicitly—not a blind "microservices must HTTP" rule.
"""

from __future__ import annotations

COLLECTION_REALTOR = "Realtors"
COLLECTION_INTERNAL = "Internals"


def collection_for_role(role: str) -> str:
    if role == "realtor":
        return COLLECTION_REALTOR
    if role == "internal":
        return COLLECTION_INTERNAL
    raise ValueError("invalid role")


def signup_document(uid: str, email: str | None, *, document_exists: bool) -> dict:
    data: dict = {"uid": uid, "email": (email or "").strip()}
    if not document_exists:
        data["ownerUid"] = uid
        data["createdBy"] = uid
    return data


def login_document(
    uid: str, email: str | None, last_sign_in_iso: str, *, document_exists: bool
) -> dict:
    patch: dict = {"email": (email or "").strip(), "lastSignInAt": last_sign_in_iso}
    if not document_exists:
        patch["uid"] = uid
        patch["ownerUid"] = uid
        patch["createdBy"] = uid
    return patch

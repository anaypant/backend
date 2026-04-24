# ACS Internal Request Contract

This document describes how authentication and identity are conveyed across all ACS service
boundaries. Every hop between services uses one of the three patterns below.

---

## Identity Model

There are three principal types in the ACS system:

| Principal | Identifier | Claim set |
|---|---|---|
| **Realtor** (client) | Firebase UID | `role: "realtor"` |
| **Internal / Admin** (ACS developer) | Firebase UID | `role: "internal"`, `admin: true` |
| **Platform Service** (GCP service account) | SA email | Google OIDC token |

---

## Path 1 — Public Gateway (Browser → ESP → Service)

Used when a browser or mobile client hits the public-facing API Gateway (ESP/Cloud Endpoints).

```
Browser
  Authorization: Bearer <Firebase ID token>
    -> ESP (API Gateway)
         validates Firebase JWT, decodes claims
         sets X-Endpoint-API-UserInfo: <base64url JSON claims>
         replaces Authorization with its own SA OIDC for the backend hop
       -> Backend Service (integration, db/read, etc.)
            reads X-Endpoint-API-UserInfo for user identity
```

**Key headers at the backend:**

| Header | Content | Who sets it |
|---|---|---|
| `X-Endpoint-API-UserInfo` | Base64url-encoded JSON of Firebase token claims (includes `uid`/`user_id`, `role`, `admin`) | ESP |
| `Authorization` | Bearer SA OIDC (transport — not the user token) | ESP |

**Backend code:** `acs_internal.decode_endpoint_user_info_claims(request)`

---

## Path 2 — Internal Hop (Service → Service, User Context Preserved)

Used when one backend service calls another on behalf of an authenticated user (e.g., auth
service calling db/upsert after signup, or integration calling core).

```
Calling Service (e.g. auth-bundle, integration-bridge)
  Authorization: Bearer <Google OIDC — SA identity, audience = callee gateway hostname>
  X-ACS-Application-Authorization: Bearer <Firebase ID token — the end-user's token>
    -> Callee Service (e.g. db/read, db/upsert)
         verifies OIDC on Authorization (transport / IAM-level)
         verifies Firebase JWT on X-ACS-Application-Authorization for user identity
```

**Key headers:**

| Header | Content | Who sets it |
|---|---|---|
| `Authorization` | `Bearer <Google OIDC>` — service account identity, audience = `https://{callee-gateway-hostname}` | Caller |
| `X-ACS-Application-Authorization` | `Bearer <Firebase ID token>` — end-user identity | Caller |

**Legacy alias:** `X-ACS-User-Authorization` is treated identically to `X-ACS-Application-Authorization`.

**Backend code (callee):** `acs_internal.parse_bearer_header(request, acs_internal.APPLICATION_AUTHORIZATION_HEADER)`

**Backend code (caller):** `gcp_identity.fetch_id_token(Request(), audience)` for OIDC; pass user
JWT on `X-ACS-Application-Authorization`.

---

## Path 3 — Platform Service Call (Acting-As-User, No Firebase JWT)

Used when a backend service (core, integration, auth) needs to read/write Firestore on behalf
of a user without having the user's Firebase JWT (e.g., workflow execution, scheduled sync).

```
Calling Service (e.g. core-run, integration-bridge)
  Authorization: Bearer <Google OIDC — platform SA>
  X-ACS-Platform-Authorization: Bearer <Google OIDC — same token, for legacy compatibility>
  X-ACS-Acting-Uid: <Firebase UID of the user being acted on behalf of>
    -> DB Service (db/read, db/upsert, db/query, db/delete)
         verifies OIDC audience = https://{ACS_DB_GATEWAY_HOSTNAME}
         verifies SA email = ACS_PLATFORM_SERVICE_ACCOUNT_EMAIL
         uses X-ACS-Acting-Uid as the effective user uid
         grants admin-equivalent access (platform actor bypasses ownerUid checks)
```

**Key headers:**

| Header | Content | Who sets it |
|---|---|---|
| `Authorization` | `Bearer <Google OIDC>` | Caller |
| `X-ACS-Platform-Authorization` | `Bearer <Google OIDC>` (same token, redundant but required for some legacy paths) | Caller |
| `X-ACS-Acting-Uid` | Firebase UID string — the user whose data is being accessed | Caller |

**Backend code (callee):** `platform_auth.try_platform_actor(request)` — present in all four DB functions (read, upsert, query, delete).

**Backend code (caller):** `gcp_identity.id_token_for_db_gateway()` for the OIDC token.

---

## Path 4 — Platform-Only Internal Services (Core, LLM, Events)

Used when calling internal services that have no user context (just platform SA auth).

```
Calling Service
  Authorization: Bearer <Google OIDC — platform SA, audience = callee function URL>
    -> Core runner / LLM runner / Events publisher
         verifies OIDC audience
         verifies SA email = BACKEND_SERVICE_ACCOUNT_EMAIL
```

**Key headers:**

| Header | Content | Who sets it |
|---|---|---|
| `Authorization` | `Bearer <Google OIDC>` | Caller |

**Environment variables required on callee:**

| Service | Audience env var | SA email env var |
|---|---|---|
| core-run | `CORE_INTERNAL_GATEWAY_HOSTNAME` | `BACKEND_SERVICE_ACCOUNT_EMAIL` |
| llm-complete | `LLM_INTERNAL_JWT_AUDIENCE` | `BACKEND_SERVICE_ACCOUNT_EMAIL` |
| events-publisher | `ACS_EVENTS_GATEWAY_HOSTNAME` | `ACS_PLATFORM_SERVICE_ACCOUNT_EMAIL` |

---

## Legacy Headers (Deprecated — Still Accepted)

| Header | Replacement |
|---|---|
| `X-ACS-User-Authorization` | `X-ACS-Application-Authorization` |
| `X-GCP-Identity` | `Authorization` (for OIDC transport) |

These are still recognized in `platform_auth.py` and `acs_internal.py` for backward compatibility
but should not be used in new callers.

---

## Header Resolution Order (End-User Identity)

When a backend handler resolves the end-user Firebase JWT, it checks headers in this order:

1. `X-Endpoint-API-UserInfo` — ESP-decoded claims (public gateway path)
2. `X-ACS-Application-Authorization` — internal hop application JWT
3. `X-ACS-User-Authorization` — legacy alias
4. `Authorization` — fallback (when no OIDC transport header is present)

**Code:** `acs_internal.END_USER_BEARER_HEADER_ORDER`

---

## Admin Authorization

A user is considered an admin if their Firebase JWT custom claims include `admin: true`.

- **How it is set:** The auth service (`backend/auth/functions/bundle/main.py`) sets
  `{"role": "internal", "admin": True}` on all internal users at signup and login, and via
  `POST /auth/internal/promote-admin`.
- **How it is checked (backend):** `_is_admin(decoded)` in each DB function — checks
  `decoded.get("admin") is True` or `decoded.get("role") == "admin"`.
- **How it is checked (frontend):** `user.getIdTokenResult().claims.admin === true` in
  `AuthContext.tsx`. Custom claims are embedded in the Firebase ID token and re-evaluated on
  each token refresh (typically every hour).
- **Admin capabilities:** Unrestricted DB reads/writes (bypasses `ownerUid` filter),
  `collectionGroup` queries, access to admin UI pages.

---

## Maintenance

- **`acs_internal.py` copies:** All copies must stay identical. Run
  `python backend/scripts/check_acs_internal_sync.py` to verify. Use
  `python backend/scripts/sync_acs_internal.py` to propagate the canonical
  (`integration/functions/bundle/acs_internal.py`) to all bundle copies.
- **Adding a new internal service:** Follow Path 3 or Path 4. Create a `platform_auth.py`
  in the bundle using the same pattern as `db/functions/read/platform_auth.py` or
  `core/functions/runner/platform_auth.py`. Add the gateway hostname / JWT audience as an
  env var and wire it through Terraform.

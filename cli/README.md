# ACS CLI

A Python command-line interface to authenticate and exercise every deployed ACS
backend service. Designed for use by developers and AI agents.

## Setup

```bash
cd backend/cli
pip install -r requirements.txt
```

Run commands via `python -m backend.cli.acs` from the repo root, or directly:

```bash
cd backend/cli
python acs.py --help
```

For convenience you can create an alias:

```bash
alias acs="python /path/to/backend/cli/acs.py"
```

---

## Auth

All commands that hit protected endpoints require a valid Firebase ID token.
The session is stored at `~/.acs-cli/session.json` and is refreshed automatically.

### Login (email + password)

```bash
python acs.py auth login \
  --base-url https://acs-public-9l1ydz27.uc.gateway.dev \
  --email you@example.com \
  --password yourpassword \
  --firebase-api-key AIzaSy... \
  --role realtor       # or: internal
```

`--firebase-api-key` can also be set via `FIREBASE_WEB_API_KEY` env var.
`--base-url` can also be set via `ACS_API_URL` env var.

### Login (Google ID token)

```bash
python acs.py auth login \
  --base-url https://... \
  --google-token "eyJhb..." \
  --firebase-api-key AIzaSy...
```

### Session info

```bash
python acs.py auth status
python acs.py whoami      # alias
```

### Logout

```bash
python acs.py auth logout
```

---

## Global flags

| Flag | Description |
|------|-------------|
| `--base-url URL` | Override the ACS gateway URL (also: `ACS_API_URL` env var) |
| `--raw` | Print raw JSON without the HTTP status prefix |

---

## Commands

### `health`

```bash
python acs.py health
```

Unauthenticated gateway liveness check (`GET /health`).

---

### `db`

#### `db read`

```bash
python acs.py db read --path "Realtors/abc123uid"
```

#### `db query`

```bash
# All realtors (admin only — no ownerUid filter)
python acs.py db query --path "Realtors" --limit 20

# Filtered query
python acs.py db query --path "Realtors" \
  --filter ownerUid == abc123 \
  --limit 10

# With ordering
python acs.py db query --path "Realtors/uid/WorkflowActivity" \
  --order createdAt DESC \
  --limit 50
```

`--filter` takes three arguments: `FIELD OP VALUE`. Repeat for multiple filters.

#### `db upsert`

```bash
python acs.py db upsert \
  --path "Realtors/abc123uid" \
  --data '{"displayName": "Test User", "ownerUid": "abc123uid"}'

# Full overwrite (not merge):
python acs.py db upsert --path "Realtors/abc123uid" --data '{}' --no-merge
```

---

### `core`

#### `core run`

Execute a registered Glyde workflow:

```bash
python acs.py core run \
  --workflow lead.scoring_v1 \
  --uid abc123uid

# With custom payload
python acs.py core run \
  --workflow contact.enrichment_v1 \
  --uid abc123uid \
  --payload '{"canonicalLeadId": "lead_xyz"}'

# Volatile mode (allow live external actions)
python acs.py core run \
  --workflow communication.auto_reply_v1 \
  --uid abc123uid \
  --volatile
```

Available workflow IDs (from `core catalog`):
- `appointment.prep_v1`
- `lead.scoring_v1`
- `communication.auto_reply_v1`
- `campaign.drip_v1`
- `ads.management_v1`
- `lead.hot_notify_v1`
- `contact.enrichment_v1`
- `migration.import_leads_v1`
- `analytical.stub_v1`

> Requires `ACS_ENABLE_DEV_LAB=1` is **not** needed for `core run` — it uses the normal
> workflow execution path.

#### `core catalog`

List all registered workflows and tools (requires `ACS_ENABLE_DEV_LAB=1`):

```bash
python acs.py core catalog
```

#### `core tool`

Run a single registered tool directly:

```bash
python acs.py core tool \
  --id db.merge_realtor_profile \
  --args '{"uid": "abc123uid", "fields": {"displayName": "Hello"}}' \
  --uid abc123uid
```

Requires `ACS_ENABLE_DEV_LAB=1`.

#### `core checks`

Run core unit checks:

```bash
python acs.py core checks --uid abc123uid
```

Requires `ACS_ENABLE_DEV_LAB=1`.

---

### `integration`

#### `integration status`

```bash
python acs.py integration status
```

#### `integration unit-checks`

Run deterministic mapping/routing checks (no live FUB API call):

```bash
python acs.py integration unit-checks
```

#### `integration webhook`

Simulate a FUB webhook event through the full pipeline:

```bash
# Uses built-in default payload for personCreated
python acs.py integration webhook --event personCreated

# Custom payload
python acs.py integration webhook \
  --event personUpdated \
  --payload '{"person": {"id": 42, "stage": "Active Buyer"}}'

# Pin to a specific workflow
python acs.py integration webhook \
  --event personCreated \
  --workflow-id contact.enrichment_v1
```

Supported event types with default payloads:
`personCreated`, `personUpdated`, `noteCreated`, `taskCreated`, `appointmentCreated`

#### `integration resync-webhooks`

Re-register FUB webhook subscriptions for the authenticated user:

```bash
python acs.py integration resync-webhooks
```

---

### `admin`

#### `admin promote`

Promote a user to `admin: true` with realtor role (same claims needed for **Atom** and ACS operator tools). The caller must already have `admin: true` (or platform service-account OIDC).

```bash
python acs.py admin promote --uid d0ihHKrh7xVhpALiVRFOLCzeA0h1
```

After promotion, the user must refresh their Firebase ID token (sign out/in or wait for refresh) before Atom recognizes admin access.

---

## Agent usage patterns

The CLI is designed to be driven non-interactively. All parameters are flags
(no interactive prompts). Exit code is non-zero on HTTP errors, so agents can
detect failures:

```bash
# Check overall system health before running tests
python acs.py health || echo "Gateway unreachable"

# Login and verify
python acs.py auth login --email ... --password ... --firebase-api-key ...
python acs.py auth status

# Run a quick smoke test across all services
python acs.py health
python acs.py db query --path "Realtors" --filter ownerUid == $MY_UID --limit 1
python acs.py core catalog
python acs.py integration status
python acs.py integration unit-checks
python acs.py core checks --uid $MY_UID

# Exercise a workflow end-to-end
python acs.py integration webhook --event personCreated --workflow-id contact.enrichment_v1
python acs.py core run --workflow contact.enrichment_v1 --uid $MY_UID

# Use --raw for JSON piping
python acs.py db query --path "Realtors" --limit 5 --raw | jq '.items[].id'
```

---

## Token lifecycle

- Tokens expire after ~1 hour.
- The CLI silently refreshes via `https://securetoken.googleapis.com/v1/token`
  whenever the token has less than 60 seconds remaining.
- Requires `firebase_api_key` stored in `~/.acs-cli/session.json` at login time
  (sourced from `--firebase-api-key` or `FIREBASE_WEB_API_KEY`).

## Out of scope

The following endpoints require **platform Service Account OIDC** (not a user
Firebase token) and are not covered by this CLI:

- `POST /llm/v1/complete`
- `POST /secrets/v1/*`
- `POST /events/v1/publish`
- FUB OAuth browser flow (`/integrations/followupboss/oauth/start`)

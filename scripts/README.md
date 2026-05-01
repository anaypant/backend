# backend/scripts

Utility scripts for validating and maintaining the ACS infrastructure.
Run these before every deploy to catch configuration drift early.

---

## check_routes.py — Gateway route parity check

### Why it exists

The ACS request chain for all integration paths is two hops:

```
Client
  → Public API Gateway      (backend/api/gateway.tf)
  → Internal Integration GW (backend/integration/api/main.tf)
  → Integration Cloud Function
```

Both gateways must explicitly declare every integration route.  If a route
is added to the **public** gateway but omitted from the **internal** gateway,
the request is accepted by the public layer and then silently rejected with:

    {"message": "The current request is not defined by this API.", "code": 404}

This is easy to miss because the error looks like a network problem, not a
configuration problem.

### Usage

```bash
# From the repo root or the backend/ directory:
python backend/scripts/check_routes.py
```

Exit code **0** — all integration routes are in parity, safe to deploy.  
Exit code **1** — one or more routes are missing from the internal gateway.

### When to run it

- Before every `terraform apply` that touches `backend/api/gateway.tf`
  or `backend/integration/api/main.tf`.
- In CI as a required pre-deploy step.

### Adding a new integration route

1. Register the handler in `backend/integration/functions/bundle/routes/public_api.py`.
2. Implement the handler in the appropriate provider module.
3. Add the **same** path to **both** `backend/api/gateway.tf` (`integration_proxy_paths`) and
   `backend/integration/api/main.tf` (`integration_paths`).  For almost all FUB routes the
   public block uses `x-google-backend.address = "${local.integration_internal_base}/…/"`.
   **Exception:** `GET /integrations/followupboss/oauth/callback` proxies to `callback_bridge`
   instead — `check_routes.py` accounts for that.
4. Run `python backend/scripts/check_routes.py` — confirm exit 0.
5. Deploy via HCP Terraform (public + internal integration gateways).

---

## e2e_lead_intel_deployed.py — Lead intel + lane PM checklist (deployed gateway)

Runs against `~/.acs-cli/session.json` and writes an artifact folder under `backend/e2e_runs/`.

```bash
cd backend
python scripts/e2e_lead_intel_deployed.py
python scripts/e2e_lead_intel_deployed.py --test-lead-lane-api
```

- **Default run:** snapshots include `glydeLeadLane`, pin fields, `glydeQuarantined`, and `GlydeSettings.leadLaneAutoMode` in `quality_extracts` (plus `http.glyde_settings_read`). `QUALITY_GATES.json` adds lane-vs-tier warnings; `ENRICHMENT_QUALITY.md` adds lane rows and §1b when `--test-lead-lane-api` was used.
- **`--test-lead-lane-api`:** after `contact.intel_delta_v1`, probes `POST /integrations/glyde/leads/lane` (empty body → 400, invalid lane → 400, set nurture pinned → 200), then **restores** active + unpinned (`16e`), saves `16b`–`16e` JSON, and fails the run if the nurture write does not succeed. Pair with **Api Health Suite → Glyde routes** in the lite frontend after deploy.

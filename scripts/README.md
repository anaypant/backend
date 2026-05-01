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

1. Add the route to `backend/api/gateway.tf` under `integration_proxy_paths`
   with `"x-google-backend".address = "${local.integration_internal_base}/..."`.
2. Add the **same** path to `backend/integration/api/main.tf` under
   `integration_paths`, using `"x-google-backend" = local.integration_backend`
   and `security = []`.
3. Run `python backend/scripts/check_routes.py` — confirm exit 0.
4. Register the handler in `backend/integration/functions/bundle/routes/public_api.py`.
5. Implement the handler in the appropriate provider module.
6. Deploy via HCP Terraform.

# Post-run analysis (2026-05-01)

## What ran

- Live gateway + `~/.acs-cli/session.json`
- FUB OAuth was expired on first attempt; **`POST /integrations/followupboss/refresh`** fixed it (script updated to call this before `people/create`).
- Created person **id=170**, tags, `lastName` material change, `webhook_test` for `peopleUpdated`, DB snapshots after each wait.

## Findings

### 1. `contact.intel_delta_v1` failed on core (HTTP 500)

`webhook_dispatch` showed `contact.intel_delta_v1` → **500**, `lead.scoring_v1` → **200**.

Isolated run with `?workflowId=contact.intel_delta_v1` captured `metadata.core.detail`:

- **`NameError: name 'lazy' is not defined`** in `web_research/pipeline.py` inside `_pipeline_meta` (referenced `lazy` without passing it into the helper).

### 2. Repo fix (deploy to pick up)

- **`_pipeline_meta(..., *, lazy: bool = False)`** and all call sites pass **`lazy=lazy`**.

After redeploying core, re-run:

```text
python scripts/e2e_lead_intel_deployed.py
```

### 3. Firestore intel vs scoring

- **`InternalClients/followupboss_170`**: `acsIntel.snapshot` appeared after create path (404 → 200); `lastWebSummary` / `lastEnrichmentTier` were still empty in snapshots — consistent with delta failing before a full persist path, or enrichment writing a minimal snapshot.
- **`Leads/followupboss_170`**: `glydeScore` present (e.g. **23**) after updates — scoring path healthy.

### 4. `workflow_debug` caveat

On multi-workflow `webhook_test`, **`workflow_debug` reflects the last core response** (here scoring), not the first failed workflow. The script now adds step **`16_webhook_test_intel_delta_only.json`** to capture delta-only errors.

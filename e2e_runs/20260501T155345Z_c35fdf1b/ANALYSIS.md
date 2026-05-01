# Post-deploy verification (2026-05-01)

## Result: pass

After the `pipeline._pipeline_meta(lazy=...)` fix shipped:

- **`14_webhook_test_people_updated.json`**: `webhook_dispatch` → **`contact.intel_delta_v1` HTTP 200**, **`lead.scoring_v1` HTTP 200** (no `partial_core_error`).
- **`16_webhook_test_intel_delta_only.json`**: delta-only run **`core_http_status` 200**, `metadata_core.workflow_id` = `contact.intel_delta_v1`, `status` completed.

## Firestore signals (person **171**)

- **`lastEnrichmentTier`**: `lazy` after create path → **`intel_delta`** after material `lastName` change + webhook_test path (see `_analysis_hints` in sibling JSON).
- **`Leads/followupboss_171`**: `glydeScore` **23**, `glydeScoreUpdatedAt` present.

## Artifacts

All request/response JSON and `SUMMARY.md` live in this directory (`01_` … `17_`).

# Enrichment quality — E2E snapshot

- **run_id:** `20260501T181442Z_a5e6f9fd`
- **person_id:** `174`
- **probe_email:** `acs.leadintel.25b090d092@example.com`
- **captured_at:** `2026-05-01T18:18:00.095159+00:00`

## 1. Verdict (product signal, not CI gates)

| Signal | Value | Interpretation |
|--------|-------|----------------|
| Stored tier | `intel_delta` | intel_delta (material-field refresh + optional mini-research) |
| `lastWebSummary` length | **0** | empty — empty is common for **invalid/example email** + lazy tier |
| FUB notes (ACS) | **1** note(s), max **117** chars | adequate (short update) |
| `glydeScore` | **18** | Lead scoring output present (0–100 scale); rationale lives in workflow metadata, not always in Firestore |
| `glydeLeadLane` / pin | **`nurture`** / pinned=True | Active vs nurture (intel/enrichment cost); pin blocks auto lane from scoring |
| `glyde_settings.leadLaneAutoMode` | **`None`** | When `on`, scoring may update lane for unpinned leads |
| `glydeQuarantined` | **`None`** | Drip-only flag; independent of lane (PM v1) |
| Snapshot vs FUB name | **aligned** | Firestore `acsIntel.snapshot.display_name` vs FUB `name` |
| Primary email status (FUB) | `Invalid` | Invalid → web research rarely finds real identity |

## 1b. Lead lane API (E2E flag `--test-lead-lane-api`)

Artifacts: `16b_lane_api_empty_body.json`, `16c_lane_api_invalid_lane.json`, `16d_lane_api_set_nurture_pinned.json`.

```json
{
  "canonical_lead_id": "followupboss_174",
  "empty_body_http": 400,
  "bad_lane_http": 400,
  "set_nurture_http": 200,
  "empty_body_ok": true,
  "bad_lane_ok": true,
  "set_ok": true
}
```

## 2. Rubric (how good was this enrichment for a realtor?)

| Expectation | Grade | Notes |
|-------------|-------|-------|
| Pipeline ran end-to-end | **Strong** | Webhooks + workflows + Firestore reads succeeded |
| Tiering behaves | **Strong** | `lastEnrichmentTier` from final snapshot |
| Research summary usefulness | **Low** | Driven by signal strength + tier + email validity |
| CRM note (delta / ACS) | **Strong** | First-party FUB `notes/list` bodies |
| Score actionable | **OK** | Number without qualitative rationale in this export |

## 3. What to read in artifacts

- **`18_final_enriched_snapshot.json`** — full FUB person, notes, `InternalClients` + `Leads` + optional `BillingUsage` + **lane fields** in `quality_extracts` / `http.glyde_settings_read`.
- **`16b_lane_api_empty_body.json`** … **`16d_lane_api_set_nurture_pinned.json`** — only when run with `--test-lead-lane-api`.
- **`local_mirror/enriched_contact_full.json`** — same payload.
- **`_analysis_hints.json`** — tier + summary length after each phase (07/10/13/15).

## 4. ACS / delta note excerpts (FUB)

### Note 1

```
ACS update — display_name changed in Follow Up Boss. Intel was refreshed; little additional public context was found.
```

## 5. Web research summary (`acsIntel.lastWebSummary`)

_Empty in this run._

## 6. Stored snapshot (identity slice)

```json
{
  "display_name": "Acs LeadIntel-25b090d092-delta7e31",
  "person_id": 174,
  "emails": [
    "acs.leadintel.25b090d092@example.com"
  ],
  "phones": []
}
```

## 7. Usage meter (month doc, if present)

```json
{
  "workflowRunCounts": {
    "contact.intel_delta_v1": 4,
    "contact.enrichment_v1": 4
  },
  "lazySnapshotRuns": 4,
  "intelDeltaRuns": 4,
  "fullSnapshotRuns": 0,
  "lastUsageTier": "intel_delta",
  "lastWorkflowId": "contact.intel_delta_v1",
  "spentUsd": 0.000738,
  "searchApiCalls": 8,
  "lastUpdatedSearch": "duckduckgo",
  "llmTokensInEstimated": 17032,
  "llmTokensOutEstimated": 1258,
  "enrichmentsTotal": 8,
  "enrichmentsPremium": 8,
  "enrichmentsStandard": 0
}
```

## 8. Automated quality warnings (from harness)

```json
[
  "glyde settings doc HTTP 404 (optional \u2014 no GlydeSettings yet)",
  "lastWebSummary empty \u2014 common for lazy + low-signal email; not a hard fail"
]
```

**Tip:** For a richer `lastWebSummary`, re-run with `--business-email` set to a **reachable business domain** (or `ACS_E2E_BUSINESS_EMAIL`) so web research has real anchors.

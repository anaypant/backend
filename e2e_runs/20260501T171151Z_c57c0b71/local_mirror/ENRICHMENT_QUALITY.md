# Enrichment quality — E2E snapshot

- **run_id:** `20260501T171151Z_c57c0b71`
- **person_id:** `173`
- **probe_email:** `acs.leadintel.51db888ce4@example.com`
- **captured_at:** `2026-05-01T17:16:21.176693+00:00`

## 1. Verdict (product signal, not CI gates)

| Signal | Value | Interpretation |
|--------|-------|----------------|
| Stored tier | `intel_delta` | intel_delta (material-field refresh + optional mini-research) |
| `lastWebSummary` length | **0** | empty — empty is common for **invalid/example email** + lazy tier |
| FUB notes (ACS) | **1** note(s), max **117** chars | adequate (short update) |
| `glydeScore` | **26** | Lead scoring output present (0–100 scale); rationale lives in workflow metadata, not always in Firestore |
| Snapshot vs FUB name | **aligned** | Firestore `acsIntel.snapshot.display_name` vs FUB `name` |
| Primary email status (FUB) | `Invalid` | Invalid → web research rarely finds real identity |

## 2. Rubric (how good was this enrichment for a realtor?)

| Expectation | Grade | Notes |
|-------------|-------|-------|
| Pipeline ran end-to-end | **Strong** | Webhooks + workflows + Firestore reads succeeded |
| Tiering behaves | **Strong** | `lastEnrichmentTier` from final snapshot |
| Research summary usefulness | **Low** | Driven by signal strength + tier + email validity |
| CRM note (delta / ACS) | **Strong** | First-party FUB `notes/list` bodies |
| Score actionable | **OK** | Number without qualitative rationale in this export |

## 3. What to read in artifacts

- **`18_final_enriched_snapshot.json`** — full FUB person, notes, `InternalClients` + `Leads` + optional `BillingUsage`.
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
  "display_name": "Acs LeadIntel-51db888ce4-deltac43b",
  "person_id": 173,
  "emails": [
    "acs.leadintel.51db888ce4@example.com"
  ],
  "phones": [
    "+1555b888ce4"
  ]
}
```

## 7. Usage meter (month doc, if present)

```json
{
  "workflowRunCounts": {
    "contact.enrichment_v1": 3,
    "contact.intel_delta_v1": 3
  },
  "lazySnapshotRuns": 3,
  "intelDeltaRuns": 3,
  "fullSnapshotRuns": 0,
  "lastUsageTier": "intel_delta",
  "lastWorkflowId": "contact.intel_delta_v1",
  "spentUsd": 0.000551,
  "searchApiCalls": 6,
  "lastUpdatedSearch": "duckduckgo",
  "llmTokensInEstimated": 12631,
  "llmTokensOutEstimated": 958,
  "enrichmentsTotal": 6,
  "enrichmentsPremium": 6,
  "enrichmentsStandard": 0
}
```

## 8. Automated quality warnings (from harness)

```json
[
  "lastWebSummary empty \u2014 common for lazy + low-signal email; not a hard fail",
  "stress: lastWebSummary < 40 chars \u2014 research may be starved or blocked"
]
```

**Tip:** For a richer `lastWebSummary`, re-run with `--business-email` set to a **reachable business domain** (or `ACS_E2E_BUSINESS_EMAIL`) so web research has real anchors.

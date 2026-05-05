# PM — Lead lane lifecycle (cold ↔ warm ↔ operator)

Automated matrix on the **deployed** stack using two disposable FUB people. For this run, **`leadLaneAutoMode` is temporarily set to `on`** (restored in `pm_lc_ZZ_settings_restore.json`).

- **run_id:** `20260501T190138Z_b032d439`
- **uid:** `d0ihHKrh7xVhpALiVRFOLCzeA0h1`
- **Person A (cold arc):** `178`
- **Person B (warm + operator arc):** `179`

## Storyboard

| Arc | Intent |
|-----|--------|
| **Cold ingress** | Person A: example email, **no phone** — thin graph, expect low score / nurture tendency. |
| **Cold → warm** | Add phone + `peopleUpdated` — expect score or lane to move toward **active** when automation is on. |
| **Warm ingress** | Person B: phone + stronger primary email — richer signal vs A. |
| **Active → nurture** | Operator `POST /integrations/glyde/leads/lane` **nurture** + **pinned** on B. |
| **Nurture → active** | Operator **active** + **unpinned** — hand back to automation. |
| **Scoring nudge** | Minor FUB field + webhook on B — lane may move under policy while unpinned. |

> **Reading `lastEnrichmentTier`:** this is the label from the **last completed** enrichment/intel run; it can lag a lane change until the next workflow.

## Metrics by step

| Step | Person | Score | Lane | Pinned | Tier | FUB phones | FUB emails | Summary len |
|------|--------|-------|------|--------|------|------------|------------|---------------|
| S1_cold_baseline | 178 | 13 | nurture | None | lazy | 0 | 1 | 0 |
| S2_after_warmup_A | 178 | 21 | nurture | None | intel_delta | 1 | 1 | 0 |
| S4_warm_ingress_B | 179 | 39 | nurture | None | lazy | 1 | 1 | 0 |
| S6_active_to_nurture_B | 179 | 39 | nurture | True | lazy | 1 | 1 | 0 |
| S8_nurture_to_active_B | 179 | 39 | active | False | lazy | 1 | 1 | 0 |
| S10_scoring_nudge_B | 179 | 39 | nurture | False | lazy | 1 | 1 | 0 |

## Gates (robustness)

```json
{
  "passed": true,
  "failures": [],
  "warnings": [
    "Person A: stayed nurture after adding phone \u2014 policy may still classify as nurture until next score cycle."
  ]
}
```

_Failures block a green PM sign-off; warnings are informational._

# Lead intelligence E2E run

- run_id: `20260501T181442Z_a5e6f9fd`
- uid: `d0ihHKrh7xVhpALiVRFOLCzeA0h1`
- person_id: `174`
- probe_email: `acs.leadintel.25b090d092@example.com`
- internal_clients: `Realtors/d0ihHKrh7xVhpALiVRFOLCzeA0h1/InternalClients/followupboss_174`
- leads: `Realtors/d0ihHKrh7xVhpALiVRFOLCzeA0h1/Leads/followupboss_174`
- **lead lane API E2E:** see `16b`–`16d` JSON, `QUALITY_GATES.json` → `lead_lane_api_e2e`, and ENRICHMENT_QUALITY §1b
- guardrailLevel_before: `1`
- local_mirror: `C:\Users\anayp\Documents\acs\backend\e2e_runs\20260501T181442Z_a5e6f9fd\local_mirror`
- workspace_copy: `C:\Users\anayp\Documents\acs\backend\local_test_mirror`

## Enrichment quality (human-readable)

See **[ENRICHMENT_QUALITY.md](./ENRICHMENT_QUALITY.md)** for rubric, excerpts, usage slice, and interpretation.

## Quality gates

```json
{
  "passed": true,
  "failures": [],
  "warnings": [
    "glyde settings doc HTTP 404 (optional \u2014 no GlydeSettings yet)",
    "lastWebSummary empty \u2014 common for lazy + low-signal email; not a hard fail"
  ],
  "lead_lane_api_e2e": {
    "canonical_lead_id": "followupboss_174",
    "empty_body_http": 400,
    "bad_lane_http": 400,
    "set_nurture_http": 200,
    "empty_body_ok": true,
    "bad_lane_ok": true,
    "set_ok": true
  },
  "hints": {
    "intel_delta_only_core_http": 200,
    "webhook_test_workflow_debug_present": true,
    "webhook_dispatch": [
      {
        "workflow_id": "contact.intel_delta_v1",
        "core_http_status": 200
      },
      {
        "workflow_id": "lead.scoring_v1",
        "core_http_status": 200
      }
    ],
    "volatile_external_allowed_in_debug": true,
    "workflow_audit_nodes_count": null,
    "intel_after_create": {
      "http": 200,
      "lastEnrichmentTier": "lazy",
      "lastEnrichedAt": "2026-05-01T18:15:30.925193+00:00",
      "summary_len": 0
    },
    "intel_after_tags": {
      "http": 200,
      "lastEnrichmentTier": "lazy",
      "lastEnrichedAt": "2026-05-01T18:15:30.925193+00:00",
      "summary_len": 0
    },
    "intel_after_lastname": {
      "http": 200,
      "lastEnrichmentTier": "intel_delta",
      "lastEnrichedAt": "2026-05-01T18:16:45.364529+00:00",
      "summary_len": 0
    },
    "intel_after_webhook_test": {
      "http": 200,
      "lastEnrichmentTier": "intel_delta",
      "lastEnrichedAt": "2026-05-01T18:16:45.364529+00:00",
      "summary_len": 0
    },
    "final_glydeLeadLane": "nurture",
    "final_glydeLaneUserPinned": true,
    "final_leadLaneAutoMode_setting": null
  }
}
```

## Log

```
=== E2E lead intel run 20260501T181442Z_a5e6f9fd uid=d0ihHKrh… === stress=False poll=120.0s ===
01 health HTTP 200
02 fub/status HTTP 200
03 profile read HTTP 200 guardrailLevel_before=1
04 profile hands-on HTTP 200
04b fub/oauth refresh HTTP 200
05 people/create HTTP 201
    person_id=174 email=acs.leadintel.25b090d092@example.com
06 polling intel up to 120.0s after create (min sleep 35.0s)…
    … polling InternalClients (119s left) http=404
    … polling InternalClients (115s left) http=404
    … polling InternalClients (111s left) http=404
07 db/read internal HTTP 200 leads HTTP 404
    snapshot 07 notes=0
08 tags/add HTTP 200
09 sleeping 25.0s after tags…
10 db/read internal HTTP 200 leads HTTP 200
    snapshot 10 notes=0
11 people/update lastName HTTP 200 -> 'LeadIntel-25b090d092-delta7e31'
12 sleeping 35.0s after lastName update…
13 db/read internal HTTP 200 leads HTTP 200
    snapshot 13 notes=1
14 webhook_test peopleUpdated HTTP 200
15 db/read internal HTTP 200 leads HTTP 200
    snapshot 15 notes=1
16 webhook_test intel_delta only HTTP 200
16b–16d glyde/leads/lane probes canonical=followupboss_174 http=400/400/200
--- analysis hints ---
  intel_delta_only_core_http: 200
  webhook_test_workflow_debug_present: True
  webhook_dispatch: [{'workflow_id': 'contact.intel_delta_v1', 'core_http_status': 200}, {'workflow_id': 'lead.scoring_v1', 'core_http_status': 200}]
  volatile_external_allowed_in_debug: True
  workflow_audit_nodes_count: None
  intel_after_create: {'http': 200, 'lastEnrichmentTier': 'lazy', 'lastEnrichedAt': '2026-05-01T18:15:30.925193+00:00', 'summary_len': 0}
  intel_after_tags: {'http': 200, 'lastEnrichmentTier': 'lazy', 'lastEnrichedAt': '2026-05-01T18:15:30.925193+00:00', 'summary_len': 0}
  intel_after_lastname: {'http': 200, 'lastEnrichmentTier': 'intel_delta', 'lastEnrichedAt': '2026-05-01T18:16:45.364529+00:00', 'summary_len': 0}
  intel_after_webhook_test: {'http': 200, 'lastEnrichmentTier': 'intel_delta', 'lastEnrichedAt': '2026-05-01T18:16:45.364529+00:00', 'summary_len': 0}
  final_glydeLeadLane: nurture
  final_glydeLaneUserPinned: True
  final_leadLaneAutoMode_setting: None
--- quality gates ---
{
  "passed": true,
  "failures": [],
  "warnings": [
    "glyde settings doc HTTP 404 (optional \u2014 no GlydeSettings yet)",
    "lastWebSummary empty \u2014 common for lazy + low-signal email; not a hard fail"
  ],
  "lead_lane_api_e2e": {
    "canonical_lead_id": "followupboss_174",
    "empty_body_http": 400,
    "bad_lane_http": 400,
    "set_nurture_http": 200,
    "empty_body_ok": true,
    "bad_lane_ok": true,
    "set_ok": true
  },
  "hints": {
    "intel_delta_only_core_http": 200,
    "webhook_test_workflow_debug_present": true,
    "webhook_dispatch": [
      {
        "workflow_id": "contact.intel_delta_v1",
        "core_http_status": 200
      },
      {
        "workflow_id": "lead.scoring_v1",
        "core_http_status": 200
      }
    ],
    "volatile_external_allowed_in_debug": true,
    "workflow_audit_nodes_count": null,
    "intel_after_create": {
      "http": 200,
      "lastEnrichmentTier": "lazy",
      "lastEnrichedAt": "2026-05-01T18:15:30.925193+00:00",
      "summary_len": 0
    },
    "intel_after_tags": {
      "http": 200,
      "lastEnrichmentTier": "lazy",
      "lastEnrichedAt": "2026-05-01T18:15:30.925193+00:00",
      "summary_len": 0
    },
    "intel_after_lastname": {
      "http": 200,
      "lastEnrichmentTier": "intel_delta",
      "lastEnrichedAt": "2026-05-01T18:16:45.364529+00:00",
      "summary_len": 0
    },
    "intel_after_webhook_test": {
      "http": 200,
      "lastEnrichmentTier": "intel_delta",
      "lastEnrichedAt": "2026-05-01T18:16:45.364529+00:00",
      "summary_len": 0
    },
    "final_glydeLeadLane": "nurture",
    "final_glydeLaneUserPinned": true,
    "final_leadLaneAutoMode_setting": null
  }
}
17 profile restore guardrailLevel=1 HTTP 200
```

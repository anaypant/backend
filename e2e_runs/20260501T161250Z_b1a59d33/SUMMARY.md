# Lead intelligence E2E run

- run_id: `20260501T161250Z_b1a59d33`
- uid: `d0ihHKrh7xVhpALiVRFOLCzeA0h1`
- person_id: `172`
- probe_email: `acs.leadintel.2c52df65a0@example.com`
- internal_clients: `Realtors/d0ihHKrh7xVhpALiVRFOLCzeA0h1/InternalClients/followupboss_172`
- leads: `Realtors/d0ihHKrh7xVhpALiVRFOLCzeA0h1/Leads/followupboss_172`
- guardrailLevel_before: `1`
- local_mirror: `C:\Users\anayp\Documents\acs\backend\e2e_runs\20260501T161250Z_b1a59d33\local_mirror`
- workspace_copy: `C:\Users\anayp\Documents\acs\backend\local_test_mirror`

## Quality gates

```json
{
  "passed": false,
  "failures": [
    "HTTP 404 on notes_list",
    "hands-on: no FUB note body contains 'ACS' (expected createNote from workflows)"
  ],
  "warnings": [
    "hands-on: no long ACS note (>80 chars) \u2014 notes may be very short",
    "lastWebSummary empty \u2014 common for lazy + low-signal email; not a hard fail",
    "stress: lastWebSummary < 40 chars \u2014 research may be starved or blocked"
  ],
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
      "lastEnrichedAt": "2026-05-01T16:13:33.833595+00:00",
      "summary_len": 0
    },
    "intel_after_tags": {
      "http": 200,
      "lastEnrichmentTier": "lazy",
      "lastEnrichedAt": "2026-05-01T16:13:33.833595+00:00",
      "summary_len": 0
    },
    "intel_after_lastname": {
      "http": 200,
      "lastEnrichmentTier": "intel_delta",
      "lastEnrichedAt": "2026-05-01T16:14:58.961809+00:00",
      "summary_len": 0
    },
    "intel_after_webhook_test": {
      "http": 200,
      "lastEnrichmentTier": "intel_delta",
      "lastEnrichedAt": "2026-05-01T16:14:58.961809+00:00",
      "summary_len": 0
    }
  }
}
```

## Log

```
=== E2E lead intel run 20260501T161250Z_b1a59d33 uid=d0ihHKrh… === stress=True poll=240.0s ===
01 health HTTP 200
02 fub/status HTTP 200
03 profile read HTTP 200 guardrailLevel_before=1
04 profile hands-on HTTP 200
04b fub/oauth refresh HTTP 200
05 people/create HTTP 201
    person_id=172 email=acs.leadintel.2c52df65a0@example.com
06 polling intel up to 240.0s after create (min sleep 50.0s)…
    … polling InternalClients (239s left) http=404
    … polling InternalClients (235s left) http=404
    … polling InternalClients (231s left) http=404
07 db/read internal HTTP 200 leads HTTP 404
    snapshot 07 notes=0
08 tags/add HTTP 200
09 sleeping 35.0s after tags…
10 db/read internal HTTP 200 leads HTTP 200
    snapshot 10 notes=0
11 people/update lastName HTTP 200 -> 'LeadIntel-2c52df65a0-deltac3fa'
12 sleeping 45.0s after lastName update…
13 db/read internal HTTP 200 leads HTTP 200
    snapshot 13 notes=0
14 webhook_test peopleUpdated HTTP 200
15 db/read internal HTTP 200 leads HTTP 200
    snapshot 15 notes=0
stress#1 webhook_test peopleUpdated HTTP 200
stress#2 webhook_test peopleUpdated HTTP 200
stress#3 webhook_test peopleUpdated HTTP 200
stress#4 webhook_test peopleUpdated HTTP 200
16 webhook_test intel_delta only HTTP 200
--- analysis hints ---
  intel_delta_only_core_http: 200
  webhook_test_workflow_debug_present: True
  webhook_dispatch: [{'workflow_id': 'contact.intel_delta_v1', 'core_http_status': 200}, {'workflow_id': 'lead.scoring_v1', 'core_http_status': 200}]
  volatile_external_allowed_in_debug: True
  workflow_audit_nodes_count: None
  intel_after_create: {'http': 200, 'lastEnrichmentTier': 'lazy', 'lastEnrichedAt': '2026-05-01T16:13:33.833595+00:00', 'summary_len': 0}
  intel_after_tags: {'http': 200, 'lastEnrichmentTier': 'lazy', 'lastEnrichedAt': '2026-05-01T16:13:33.833595+00:00', 'summary_len': 0}
  intel_after_lastname: {'http': 200, 'lastEnrichmentTier': 'intel_delta', 'lastEnrichedAt': '2026-05-01T16:14:58.961809+00:00', 'summary_len': 0}
  intel_after_webhook_test: {'http': 200, 'lastEnrichmentTier': 'intel_delta', 'lastEnrichedAt': '2026-05-01T16:14:58.961809+00:00', 'summary_len': 0}
--- quality gates ---
{
  "passed": false,
  "failures": [
    "HTTP 404 on notes_list",
    "hands-on: no FUB note body contains 'ACS' (expected createNote from workflows)"
  ],
  "warnings": [
    "hands-on: no long ACS note (>80 chars) \u2014 notes may be very short",
    "lastWebSummary empty \u2014 common for lazy + low-signal email; not a hard fail",
    "stress: lastWebSummary < 40 chars \u2014 research may be starved or blocked"
  ],
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
      "lastEnrichedAt": "2026-05-01T16:13:33.833595+00:00",
      "summary_len": 0
    },
    "intel_after_tags": {
      "http": 200,
      "lastEnrichmentTier": "lazy",
      "lastEnrichedAt": "2026-05-01T16:13:33.833595+00:00",
      "summary_len": 0
    },
    "intel_after_lastname": {
      "http": 200,
      "lastEnrichmentTier": "intel_delta",
      "lastEnrichedAt": "2026-05-01T16:14:58.961809+00:00",
      "summary_len": 0
    },
    "intel_after_webhook_test": {
      "http": 200,
      "lastEnrichmentTier": "intel_delta",
      "lastEnrichedAt": "2026-05-01T16:14:58.961809+00:00",
      "summary_len": 0
    }
  }
}
17 profile restore guardrailLevel=1 HTTP 200
```

# Lead intelligence E2E run

- run_id: `20260501T154428Z_9aa0bab2`
- uid: `d0ihHKrh7xVhpALiVRFOLCzeA0h1`
- person_id: `170`
- probe_email: `acs.leadintel.c661331ec9@example.com`
- internal_clients: `Realtors/d0ihHKrh7xVhpALiVRFOLCzeA0h1/InternalClients/followupboss_170`
- leads: `Realtors/d0ihHKrh7xVhpALiVRFOLCzeA0h1/Leads/followupboss_170`
- guardrailLevel_before: `1`

## Log

```
=== E2E lead intel run 20260501T154428Z_9aa0bab2 uid=d0ihHKrh… ===
01 health HTTP 200
02 fub/status HTTP 200
03 profile read HTTP 200 guardrailLevel_before=1
04 profile hands-on HTTP 200
04b fub/oauth refresh HTTP 200
05 people/create HTTP 201
    person_id=170 email=acs.leadintel.c661331ec9@example.com
06 sleeping 35s for peopleCreated webhooks…
07 db/read internal HTTP 404 leads HTTP 200
08 tags/add HTTP 200
09 sleeping 25s after tags…
10 db/read internal HTTP 200 leads HTTP 200
11 people/update lastName HTTP 200 -> 'LeadIntel-c661331ec9-delta59f5'
12 sleeping 35s after lastName update…
13 db/read internal HTTP 200 leads HTTP 200
14 webhook_test peopleUpdated HTTP 200
15 db/read internal HTTP 200 leads HTTP 200
16 profile restore guardrailLevel=1 HTTP 200
--- analysis hints ---
  webhook_test_workflow_debug_present: True
  webhook_dispatch: [{'workflow_id': 'contact.intel_delta_v1', 'core_http_status': 500, 'error': 'workflow execution failed'}, {'workflow_id': 'lead.scoring_v1', 'core_http_status': 200}]
  volatile_external_allowed_in_debug: True
  workflow_audit_nodes_count: None
  intel_after_create: {'http': 404, 'lastEnrichmentTier': None, 'lastEnrichedAt': None, 'summary_len': 0}
  intel_after_tags: {'http': 200, 'lastEnrichmentTier': None, 'lastEnrichedAt': '2026-05-01T15:45:31.829282+00:00', 'summary_len': 0}
  intel_after_lastname: {'http': 200, 'lastEnrichmentTier': None, 'lastEnrichedAt': '2026-05-01T15:45:31.829282+00:00', 'summary_len': 0}
  intel_after_webhook_test: {'http': 200, 'lastEnrichmentTier': None, 'lastEnrichedAt': '2026-05-01T15:45:31.829282+00:00', 'summary_len': 0}
```

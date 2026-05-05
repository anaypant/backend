# Lead intelligence E2E run

- run_id: `20260501T190138Z_b032d439`
- uid: `d0ihHKrh7xVhpALiVRFOLCzeA0h1`
- person_id: `None`
- probe_email: `None`
- internal_clients: `None`
- leads: `None`
- **PM lane lifecycle:** see **[PM_LANE_LIFECYCLE.md](./PM_LANE_LIFECYCLE.md)** and `PM_LANE_LIFECYCLE_GATES.json`
- guardrailLevel_before: `None`
- local_mirror: `C:\Users\anayp\Documents\acs\backend\e2e_runs\20260501T190138Z_b032d439\local_mirror`
- workspace_copy: `C:\Users\anayp\Documents\acs\backend\local_test_mirror`

## PM lane lifecycle quality

This run did **not** execute the full enrichment E2E. See **PM_LANE_LIFECYCLE.md** for the cold→warm→operator matrix and gate rationale.

## Quality gates

```json
{
  "passed": true,
  "failures": [],
  "warnings": [
    "Person A: stayed nurture after adding phone \u2014 policy may still classify as nurture until next score cycle."
  ]
}
```

## Log

```
=== PM lane lifecycle only 20260501T190138Z_b032d439 uid=d0ihHKrh… stress=False ===
01 health HTTP 200
02 fub/status HTTP 200
pm_lc leadLaneAutoMode=on (will restore to 'off') HTTP 200
pm_lc Person A (cold) id=178
    … waiting Firestore Leads row (198s)
    … waiting Firestore Leads row (192s)
    … waiting Firestore Leads row (186s)
    … waiting Firestore Leads row (180s)
    … waiting Firestore Leads row (174s)
pm_lc Person B (warm) id=179 email='acs.warm.794e2d65ae@gmail.com'
    … waiting Firestore Leads row (198s)
    … waiting Firestore Leads row (192s)
    … waiting Firestore Leads row (186s)
    … waiting Firestore Leads row (181s)
    … waiting Firestore Leads row (175s)
--- PM lane lifecycle gates ---
{
  "passed": true,
  "failures": [],
  "warnings": [
    "Person A: stayed nurture after adding phone \u2014 policy may still classify as nurture until next score cycle."
  ]
}
Done PM lane lifecycle. Artifacts: C:\Users\anayp\Documents\acs\backend\e2e_runs\20260501T190138Z_b032d439
pm_lc settings restore leadLaneAutoMode='off' HTTP 200
```

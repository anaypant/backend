# Lead intelligence E2E run

- run_id: `20260501T183119Z_08e5be24`
- uid: `d0ihHKrh7xVhpALiVRFOLCzeA0h1`
- person_id: `None`
- probe_email: `None`
- internal_clients: `None`
- leads: `None`
- **PM lane lifecycle:** see **[PM_LANE_LIFECYCLE.md](./PM_LANE_LIFECYCLE.md)** and `PM_LANE_LIFECYCLE_GATES.json`
- guardrailLevel_before: `None`
- local_mirror: `C:\Users\anayp\Documents\acs\backend\e2e_runs\20260501T183119Z_08e5be24\local_mirror`
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
=== PM lane lifecycle only 20260501T183119Z_08e5be24 uid=d0ihHKrh… stress=False ===
01 health HTTP 200
02 fub/status HTTP 200
pm_lc leadLaneAutoMode=on (will restore to None) HTTP 200
pm_lc Person A (cold) id=175
    … waiting Firestore Leads row (198s)
    … waiting Firestore Leads row (192s)
    … waiting Firestore Leads row (186s)
    … waiting Firestore Leads row (180s)
pm_lc Person B (warm) id=176 email='acs.warm.8d02b4d5ed@gmail.com'
    … waiting Firestore Leads row (196s)
    … waiting Firestore Leads row (190s)
    … waiting Firestore Leads row (184s)
    … waiting Firestore Leads row (178s)
    … waiting Firestore Leads row (172s)
    … waiting Firestore Leads row (167s)
    … waiting Firestore Leads row (161s)
    … waiting Firestore Leads row (155s)
    … waiting Firestore Leads row (149s)
    … waiting Firestore Leads row (143s)
    … waiting Firestore Leads row (137s)
    … waiting Firestore Leads row (131s)
    … waiting Firestore Leads row (125s)
    … waiting Firestore Leads row (119s)
    … waiting Firestore Leads row (113s)
    … waiting Firestore Leads row (108s)
    … waiting Firestore Leads row (102s)
    … waiting Firestore Leads row (96s)
    … waiting Firestore Leads row (90s)
    … waiting Firestore Leads row (84s)
    … waiting Firestore Leads row (78s)
    … waiting Firestore Leads row (73s)
    … waiting Firestore Leads row (67s)
    … waiting Firestore Leads row (61s)
    … waiting Firestore Leads row (55s)
    … waiting Firestore Leads row (48s)
    … waiting Firestore Leads row (42s)
    … waiting Firestore Leads row (36s)
    … waiting Firestore Leads row (30s)
    … waiting Firestore Leads row (23s)
    … waiting Firestore Leads row (16s)
    … waiting Firestore Leads row (10s)
    … waiting Firestore Leads row (3s)
WARN: Person B Leads row not seen in time
--- PM lane lifecycle gates ---
{
  "passed": true,
  "failures": [],
  "warnings": [
    "Person A: stayed nurture after adding phone \u2014 policy may still classify as nurture until next score cycle."
  ]
}
Done PM lane lifecycle. Artifacts: C:\Users\anayp\Documents\acs\backend\e2e_runs\20260501T183119Z_08e5be24
pm_lc settings restore leadLaneAutoMode='off' HTTP 200
```

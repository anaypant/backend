# ACS Lead Intelligence — QA quality analysis

**Report type:** Post-deploy verification + test harness review  
**Run under analysis:** `20260501T155345Z_c35fdf1b`  
**Tester role:** Independent QA assessment (functional + product/value)  
**Date context:** 2026-05-01  

---

## 1. Executive summary

| Area | Verdict |
|------|---------|
| **Pipeline reliability** | **Pass** after deploy: `contact.intel_delta_v1` and `lead.scoring_v1` both return HTTP 200 on `peopleUpdated`; isolated delta run passes. |
| **Data continuity** | **Pass:** `InternalClients` `acsIntel.snapshot` updates across create → lazy enrichment → material edit → `intel_delta`; `display_name` reflects `lastName` change. |
| **Scoring integration** | **Pass:** `Leads` doc shows `glydeScore` and `glydeScoreUpdatedAt`; score **changed** across the run (evidence workflows re-ran). |
| **Client-visible “intel depth”** | **Risk / not proven:** `lastWebSummary` remained **empty** in captured DB snapshots; tests did **not** assert richness of research, note body, or realtor trust copy. |
| **Safety / guardrails** | **Partially tested:** Run used **hands-on** (`guardrailLevel: 1`) throughout; **analytical (safe) mode** not exercised in this pass. |
| **Test harness maturity** | **Good** for integration smoke; **weak** on content quality, negative paths, multi-tenant, and billing assertions. |

**Bottom line for product:** ACS demonstrates **technical delivery** of the lead-intelligence architecture (webhooks → workflows → Firestore). **Demonstrated client value** (actionable, trustworthy, differentiated intel) is **not yet validated** by this suite—only **eligibility** for that value.

---

## 2. What the E2E suite actually proved

### 2.1 Functional (automation log + artifacts)

1. **Gateway & auth path:** `/health` 200; session-based calls succeed.  
2. **FUB connectivity:** `/integrations/followupboss/status` 200; OAuth **refresh** before writes avoids `expired-access-token` (lesson from prior run).  
3. **Real CRM mutation:** `people/create` 201 → person **171**; subsequent `tags/add`, `people/update` 200.  
4. **Async pipeline (real FUB webhooks):** Waits + DB reads show `InternalClients` and `Leads` populated after create and after edits.  
5. **Synchronous integration → core:** `webhook_test` for `peopleUpdated` runs **both** mapped workflows with **200/200** dispatch.  
6. **Regression guard:** Dedicated `webhook_test?workflowId=contact.intel_delta_v1` confirms delta workflow **completes** in isolation (important after prior `NameError` in web research).  

### 2.2 Product signals from Firestore (run `171`)

- **`lastEnrichmentTier`:** `lazy` after create path → `intel_delta` after material field change — aligns with **tiered** snapshot vs delta story.  
- **`acsIntel.snapshot`:** `display_name` moves from `…342e8c0941` to `…342e8c0941-delta3948` — **staleness / identity refresh path** is exercised.  
- **`lastWebSummary`:** **Empty string** in stored artifacts — research pipeline may have produced no summary for this probe (lazy + weak signals + example.com email), or persistence path stores empty; **not validated as “good” intel**.  
- **Scoring:** `glydeScore` **23** (snapshot after lastName) vs **18** (after final `webhook_test`) — scoring **re-executed** and **numeric output changed**; qualitative rationale **not** captured in DB read (stored elsewhere or only in metadata).  

---

## 3. Test methodology assessment (QA rigor)

### Strengths

- **End-to-end realism:** Real FUB API + real webhooks + Firestore reads—not mocks only.  
- **Reproducible artifacts:** JSON per step + `SUMMARY.md` supports audit and triage.  
- **Failure isolation:** Delta-only `webhook_test` mitigates multi-workflow `workflow_debug` showing only the **last** core response.  
- **Operational hardening:** Explicit FUB token refresh addresses production friction.  

### Limitations (material to “quality for clients”)

| Gap | Impact |
|-----|--------|
| **No assertions on content** | Pass/fail is HTTP + coarse DB fields; a “successful” run could still ship **low-value or misleading** notes/summaries. |
| **`workflow_audit_nodes_count: null`** in hints | `workflow_debug` shape does not surface full `workflowAudit` nodes—**performance and step-level QA** limited without core API or log export. |
| **Single realtor / single environment** | No matrix across **guardrail 0 vs 1**, budget exhaustion, or **premium vs standard** search. |
| **No FUB-side verification** | Notes/tasks **not** fetched from FUB API to confirm **“ACS update —”** note quality, count, or duplicate behavior. |
| **Synthetic lead profile** | `example.com` email, minimal phone—**not representative** of business-email / high-signal leads where product differentiates. |
| **No duplicate / idempotency test** | Ledger dedupe and “no spam notes” claims **untested** here. |
| **No usage / billing ledger read** | `usage_tracker` / monthly cap behavior **not** asserted post-run. |
| **Timing sensitivity** | Fixed sleeps may **flake** under load or **miss** slow webhooks; no poll-until-stable loop. |

---

## 4. Client value assessment (realtor-centric)

Aligned to a typical **value rubric** for lead intelligence:

| Client expectation | Evidence from this test | Grade |
|--------------------|---------------------------|-------|
| “Something runs when I add a lead” | Create → DB intel + lead present | **Strong** |
| “Intel stays aligned when I fix the contact” | `lastName` change → tier + snapshot update | **Strong** |
| “I get honest, useful context—not noise” | No review of summary, sources, or note text | **Unknown** |
| “I control cost / surprise bills” | No billing usage assertions | **Unknown** |
| “Safe mode won’t spam my CRM” | Not tested in this run (hands-on only) | **Unknown** |
| “Scores help me prioritize” | Number present and updates; rationale not validated | **Partial** |

**Conclusion:** Value proposition is **proven at orchestration layer**; **not proven at experience layer** (copy, trust, restraint, economics).

---

## 5. Defects and incidents (historical)

- **P1 (fixed):** `contact.intel_delta_v1` failed with `NameError` in `web_research` `_pipeline_meta` — caught only by **live E2E**, not unit tests. **Recommendation:** keep lazy-path unit test + CI lint (see prior engineering note).  
- **P2 (mitigated):** FUB access token expiry on `people/create` — mitigated by **refresh** step in harness; product risk remains if refresh fails silently in other clients.  

---

## 6. Recommendations (prioritized)

### P0 — Before marketing “best-in-class lead intel”

1. **Content QA checklist (manual or semi-auto):** For each tier (`lazy`, `full`, `intel_delta`), require: non-empty `suggested_note` **or** explicit “insufficient data” path; **no** fabricated employer claims; **sources** when summary non-empty.  
2. **Safe-mode E2E:** Same script with `guardrailLevel: 0`; assert **no** outbound note application (or assert `skipped_by_policy` in metadata if core returns it to client).  
3. **FUB read-back:** API fetch **notes** for test `personId` after run; cap count; assert prefix / max length.  

### P1 — Scale quality engineering

4. **Representative personas:** Matrix: personal vs **business email**, with/without phone, with tags, stage changes.  
5. **Poll-until:** Replace fixed sleep with “read InternalClients `lastEnrichedAt` or Lead `glydeScoreUpdatedAt` changed or timeout.”  
6. **Billing snapshot:** After run, read `Realtors/{uid}/BillingUsage/{month}` (if exposed via same DB API) and assert counters moved for expected tiers.  

### P2 — Continuous quality

7. **Synthetic monitoring:** Scheduled minimal `webhook_test` in staging + alert on non-200.  
8. **Score quality:** Store or fetch `metadata.leadScoring` from a debug-enabled path and assert rationale length / JSON schema.  

---

## 7. Sign-off matrix (honest QA)

| Criterion | Status |
|-----------|--------|
| Release smoke — workflows execute | **Pass** |
| Data model — intel + score persisted | **Pass** |
| Client trust — accuracy & transparency of intel | **Not tested** |
| Client control — safe mode & budget | **Not tested** (this run) |
| Operational excellence — idempotency, duplicates | **Not tested** |
| Performance — latency, timeouts | **Not measured** |

**Qualified sign-off:** **“Technical readiness — lead intelligence pipeline”** ✅  
**Not signed off:** **“Client experience & value — lead intelligence”** pending P0 items.

---

## 8. References (artifacts)

- Run folder: `backend/e2e_runs/20260501T155345Z_c35fdf1b/`  
- Key files: `07_internal_clients.json`, `15_internal_clients.json`, `14_webhook_test_people_updated.json`, `16_webhook_test_intel_delta_only.json`, `15_leads.json`, `_analysis_hints.json`  

---

*Prepared as an independent QA review. Does not replace legal/compliance review or production SLO definition.*

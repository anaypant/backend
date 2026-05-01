"""Post-deploy probe: verify web research returns sources for a known person."""
import sys, json, uuid, base64
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.cli.client import request
from backend.cli.config import get_token

token = get_token()
uid = json.loads(base64.urlsafe_b64decode(token.split('.')[1] + '====').decode()).get('user_id')

def run(label, payload_person):
    run_id = uuid.uuid4().hex[:8]
    st, body = request('POST', '/core/v1/run', json={
        'workflow_id': 'contact.enrichment_v1',
        'state': {
            'state_version': 1,
            'correlation_id': f'probe_{run_id}',
            'source': {'provider': 'followupboss', 'event_type': 'person.created'},
            'user_id': uid,
            'payload': payload_person,
            'metadata': {'execution_policy': {'volatile_external_allowed': False}},
        }
    }, timeout=120)

    state   = (body or {}).get('state') or {}
    meta    = state.get('metadata') or {}
    ce      = meta.get('contactEnrichment') or {}
    wr      = ce.get('webResearch') or {}
    synth   = ce.get('synthesis') or {}
    note    = (meta.get('outboundActions') or [{}])[0].get('payload', {}).get('body', '') if meta.get('outboundActions') else ''
    errors  = state.get('errors') or []

    print(f'\n{"─"*60}')
    print(f'  {label}')
    print(f'{"─"*60}')
    print(f'  HTTP: {st}  |  wf_status: {body.get("status")}')
    print(f'  normalized display_name : {(ce.get("normalized") or {}).get("display_name")!r}')
    print(f'  web_research query      : {wr.get("query")!r}')
    print(f'  web_research mode       : {wr.get("mode")!r}')
    print(f'  web_research sources    : {wr.get("sources_count")}')
    pipeline = wr.get("pipeline") or {}
    if pipeline:
        print(f'  pipeline backend        : {pipeline.get("search_backend")!r}')
        print(f'  urls_after_blacklist    : {pipeline.get("urls_after_blacklist")}')
        print(f'  scrape_ok               : {pipeline.get("scrape_ok")}')
    print(f'  synthesis keys          : {synth.get("keys")}')
    print(f'  fallback_note           : {synth.get("fallback_note")}')
    if note:
        print(f'  note preview            : {note[:400]}')
    if errors:
        print(f'  errors                  : {errors}')
    return st, wr.get('sources_count', 0)

# ── Test A: flat payload (the bug that just got fixed) ─────────────────────
stA, srcA = run(
    "A — Flat payload: Elon Musk (famous person, real email)",
    {
        'firstName': 'Elon', 'lastName': 'Musk',
        'emails': [{'value': 'elon@spacex.com'}],
        'provider': 'followupboss', 'id': 88001,
    }
)

# ── Test B: real contact with realistic details ────────────────────────────
stB, srcB = run(
    "B — Realistic contact: Warren Buffett",
    {
        'firstName': 'Warren', 'lastName': 'Buffett',
        'emails': [{'value': 'warren@berkshire.com'}],
        'stage': 'Active Buyer',
        'provider': 'followupboss', 'id': 88002,
    }
)

# ── Test C: unknown person (common name — tests disambiguation) ────────────
stC, srcC = run(
    "C — Common name: John Smith (no email)",
    {
        'firstName': 'John', 'lastName': 'Smith',
        'stage': 'Hot Lead',
        'provider': 'followupboss', 'id': 88003,
    }
)

# ── Summary ────────────────────────────────────────────────────────────────
print(f'\n{"═"*60}')
print(f'  RESULTS SUMMARY')
print(f'{"═"*60}')
for label, st, src in [('A (Elon Musk)', stA, srcA), ('B (Warren Buffett)', stB, srcB), ('C (John Smith)', stC, srcC)]:
    ok = '✓' if st < 400 else '✗'
    src_ok = '✓' if src and src > 0 else '✗'
    print(f'  {ok} HTTP {st}  {src_ok} {src} sources  — {label}')
print()

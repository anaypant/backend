#!/usr/bin/env python3
"""
Simulate FUB webhook → inject fake ``fubPerson`` → build ACS state → optional POST /core/v1/run.

**Full workflow** (fake ``fubPerson`` from ``example_fub_person.json``, POST to real core — no FUB API):

  python scripts/simulate_fub_webhook_pipeline.py \\
    --payload scripts/example_fub_people_created.json \\
    --connection-id YOUR_FIREBASE_UID \\
    --run-core \\
    --core-url "https://YOUR_CORE_HOST/core/v1/run/" \\
    --core-bearer "$GOOGLE_OIDC_TOKEN" \\
    --volatile-ok

``--run-core`` auto-merges the fake person (same as ``--use-fake-person``). ``--core-url`` may be a gateway
origin (``https://host``) or a full ``.../core/v1/run/`` URL. Bearer is usually a Google-signed ID token
for your internal core API Gateway.

Dry-run only prints resolution + payload keys. ``--use-fake-person`` merges ``scripts/example_fub_person.json``
(or ``--fake-person PATH``). ``--run-core`` auto-loads that fake person if you did not pass ``--inject-fub-person``.

**webhook_test** (integration → real core, needs Firebase token):

  python scripts/simulate_fub_webhook_pipeline.py --payload ... --live \\
    --webhook-test-url "https://.../integrations/followupboss/webhook_test?workflowId=contact.enrichment_v1" \\
    --bearer "$FIREBASE_ID_TOKEN"
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

# Bundle root: .../integration/functions/bundle
_BUNDLE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_FAKE_PERSON = os.path.join(_SCRIPTS_DIR, "example_fub_person.json")

if _BUNDLE_ROOT not in sys.path:
    sys.path.insert(0, _BUNDLE_ROOT)

from providers.followupboss.fub_payload_person_id import person_id_from_fub_webhook_payload


def _to_acs_state(event_body: dict[str, Any], connection_id: str) -> dict[str, Any]:
    """Mirror ``webhooks._to_acs_state`` (minimal copy for offline debug)."""
    import uuid

    event_type = event_body.get("event") if isinstance(event_body.get("event"), str) else "unknown"
    correlation = event_body.get("eventId") if isinstance(event_body.get("eventId"), str) else str(uuid.uuid4())
    return {
        "state_version": 1,
        "correlation_id": correlation,
        "tenant_id": None,
        "user_id": connection_id,
        "source": {"provider": "followupboss", "event_type": event_type},
        "payload": event_body,
        "metadata": {"connection_id": connection_id},
    }


def _normalize_core_run_url(raw: str) -> str:
    """Accept gateway origin or full /core/v1/run/ URL."""
    u = raw.strip().rstrip("/")
    if "/core/v1/run" in u:
        return u if u.endswith("/") else u + "/"
    return u + "/core/v1/run/"


def _post_json(url: str, payload: dict[str, Any], bearer: str, *, timeout: int = 120) -> tuple[int, str]:
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if bearer.strip():
        headers["Authorization"] = f"Bearer {bearer.strip()}"
    req = urllib.request.Request(url, data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")


def _load_fake_person(path: str, *, sync_id: int | None) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        person = json.load(f)
    if not isinstance(person, dict):
        raise ValueError("fake person file must be a JSON object")
    out = copy.deepcopy(person)
    if isinstance(sync_id, int) and sync_id > 0:
        out["id"] = sync_id
    return out


def main() -> int:
    p = argparse.ArgumentParser(description="Simulate FUB webhook + fake fubPerson + optional core /run.")
    p.add_argument("--payload", required=True, help="Path to JSON file (raw FUB webhook body)")
    p.add_argument("--connection-id", default="debug-local-uid", help="ACS user_id (Firebase uid)")
    p.add_argument(
        "--inject-fub-person",
        default="",
        help="Path to JSON file merged as fubPerson (explicit file)",
    )
    p.add_argument(
        "--use-fake-person",
        action="store_true",
        help=f"Merge bundled fake person (override path with --fake-person); default {_DEFAULT_FAKE_PERSON!r}",
    )
    p.add_argument(
        "--fake-person",
        default="",
        help="Path to fake FUB person JSON (defaults to example_fub_person.json next to this script)",
    )
    p.add_argument(
        "--no-sync-fake-id",
        action="store_true",
        help="Keep id from fake JSON; default is to set fake person's id to webhook-resolved person id",
    )
    p.add_argument(
        "--volatile-ok",
        action="store_true",
        help="Add metadata.execution_policy.volatile_external_allowed=true (contact enrichment outbound)",
    )
    p.add_argument("--print-core-request", action="store_true", help="Print POST /core/v1/run JSON body")
    p.add_argument("--workflow-id", default="contact.enrichment_v1", help="workflow_id for core")
    p.add_argument(
        "--run-core",
        action="store_true",
        help="POST full request to core (uses fake person automatically if no --inject-fub-person)",
    )
    p.add_argument(
        "--core-url",
        default=os.environ.get("ACS_CORE_RUN_URL", ""),
        help="Full URL to POST /core/v1/run/ (or gateway origin; env ACS_CORE_RUN_URL)",
    )
    p.add_argument(
        "--core-bearer",
        default=os.environ.get("ACS_CORE_RUN_BEARER", ""),
        help="Bearer for core gateway (Google OIDC); env ACS_CORE_RUN_BEARER",
    )
    p.add_argument("--live", action="store_true", help="POST raw webhook body to integration webhook_test")
    p.add_argument("--webhook-test-url", default=os.environ.get("ACS_WEBHOOK_TEST_URL", ""), help="webhook_test URL")
    p.add_argument("--bearer", default=os.environ.get("ACS_FIREBASE_BEARER", ""), help="Firebase ID token for webhook_test")

    args = p.parse_args()
    live = args.live or os.environ.get("ACS_SIMULATE_LIVE", "").strip() in ("1", "true", "yes")

    with open(args.payload, encoding="utf-8") as f:
        body: dict[str, Any] = json.load(f)
    if not isinstance(body, dict):
        print("ERROR: payload file must be a JSON object", file=sys.stderr)
        return 2

    ev = body.get("event", "")
    pid = person_id_from_fub_webhook_payload(body)
    people_event = str(ev).lower().startswith("people")

    print("--- person resolution (fub_payload_person_id) ---")
    print(f"  event:           {ev!r}")
    print(f"  people_* event: {people_event}")
    print(f"  resolved_id:    {pid}")
    print(f"  uri:            {body.get('uri')!r}")
    print(f"  resourceIds:    {body.get('resourceIds')!r}")
    print(f"  keys (start):   {list(body.keys())}")

    fake_path = (args.fake_person or "").strip() or _DEFAULT_FAKE_PERSON
    inject_explicit = bool((args.inject_fub_person or "").strip())
    use_fake = args.use_fake_person or args.run_core or inject_explicit

    if inject_explicit:
        inj = _load_fake_person(args.inject_fub_person.strip(), sync_id=None if args.no_sync_fake_id else pid)
        body = dict(body)
        body["fubPerson"] = inj
        print(f"\n--- merged --inject-fub-person from {args.inject_fub_person!r} ---")
    elif use_fake:
        sync = None if args.no_sync_fake_id else pid
        inj = _load_fake_person(fake_path, sync_id=sync)
        body = dict(body)
        body["fubPerson"] = inj
        print(f"\n--- merged fake fubPerson from {fake_path!r} (sync_id={sync!r}) ---")
    elif args.run_core:
        print("ERROR: --run-core needs a person payload; use --use-fake-person or --inject-fub-person", file=sys.stderr)
        return 2

    if isinstance(body.get("fubPerson"), dict):
        fp = body["fubPerson"]
        print(f"  fubPerson.id: {fp.get('id')!r}  firstName: {fp.get('firstName')!r}")

    state = _to_acs_state(body, args.connection_id)
    if args.volatile_ok:
        meta = dict(state.get("metadata") or {})
        pol = dict(meta.get("execution_policy") or {})
        pol["volatile_external_allowed"] = True
        meta["execution_policy"] = pol
        state["metadata"] = meta
        print("\n--- metadata.execution_policy: volatile_external_allowed=true ---")

    pl = state.get("payload") if isinstance(state.get("payload"), dict) else {}
    print("\n--- ACS state.payload keys (as sent to core) ---")
    print(f"  {list(pl.keys())}")
    print(f"  has fubPerson: {isinstance(pl.get('fubPerson'), dict)}")

    wf = (args.workflow_id or "").strip()
    req: dict[str, Any] = {"state": state}
    if wf:
        req["workflow_id"] = wf

    if args.print_core_request or args.run_core:
        print("\n--- POST /core/v1/run body ---")
        print(json.dumps(req, indent=2))

    if args.run_core:
        raw_url = (args.core_url or "").strip()
        if not raw_url:
            print("\nERROR: --run-core requires --core-url or ACS_CORE_RUN_URL", file=sys.stderr)
            return 3
        url = _normalize_core_run_url(raw_url)
        print(f"\n--- POST {url} ---")
        status, text = _post_json(url, req, args.core_bearer)
        print(f"HTTP {status}")
        print(text[:12000])
        if status >= 400:
            return 4

    if live:
        url = (args.webhook_test_url or "").strip()
        bearer = (args.bearer or "").strip()
        if not url or not bearer:
            print(
                "\nERROR: --live requires --webhook-test-url and --bearer",
                file=sys.stderr,
            )
            return 3
        raw = json.dumps(body).encode("utf-8")
        r = urllib.request.Request(
            url,
            data=raw,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {bearer}",
            },
        )
        print(f"\n--- LIVE webhook_test {url[:96]}... ---")
        try:
            with urllib.request.urlopen(r, timeout=120) as resp:
                print(f"HTTP {resp.status}")
                print(resp.read().decode("utf-8")[:8000])
        except urllib.error.HTTPError as e:
            print(f"HTTP {e.code}", file=sys.stderr)
            print(e.read().decode("utf-8", errors="replace")[:8000], file=sys.stderr)
            return 5

    if not live and not use_fake and people_event and pid and "fubPerson" not in body:
        print(
            "\nNOTE: No fubPerson merged. Use --use-fake-person or --run-core (auto fake) or --inject-fub-person.",
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

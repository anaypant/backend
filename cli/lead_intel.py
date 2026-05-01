"""
Lead intelligence E2E helpers (FUB → webhooks → core → Firestore).

Safe vs hands-on outbound is controlled by ``Realtors/{uid}.guardrailLevel`` (0 = analytical, 1 = volatile CRM actions allowed).
"""

from __future__ import annotations

import base64
import json
import sys
import time
import uuid
from typing import Any, Optional

import click

from . import config
from .client import CliError, request
from .lead_intel_helpers import (
    canonical_lead_doc_id,
    fub_webhook_minimal_body,
    internal_client_doc_id,
    normalize_fub_webhook_event,
)


def _err(msg: str) -> None:
    click.echo(click.style(f"error: {msg}", fg="red"), err=True)
    sys.exit(1)


def _out(ctx: click.Context, status: int, body: Any) -> None:
    raw = bool(ctx.obj.get("raw"))
    if raw:
        click.echo(json.dumps(body) if isinstance(body, (dict, list)) else str(body))
    else:
        prefix = click.style(f"HTTP {status}", fg="green" if status < 400 else "red", bold=True)
        if isinstance(body, (dict, list)):
            click.echo(f"{prefix}\n{json.dumps(body, indent=2)}")
        else:
            click.echo(f"{prefix}\n{body}")
    if status >= 400:
        sys.exit(1)


def _uid_from_session() -> str:
    session = config.get_session()
    tok = session.get("id_token") or ""
    if not tok:
        _err("Not logged in. Run `acs auth login` first.")
    try:
        parts = tok.split(".")
        padded = parts[1] + "=" * (4 - len(parts[1]) % 4)
        payload = json.loads(base64.b64decode(padded.replace("-", "+").replace("_", "/")))
        uid = payload.get("user_id") or payload.get("sub")
        if isinstance(uid, str) and uid.strip():
            return uid.strip()
    except Exception:
        pass
    _err("Could not decode UID from session id_token.")


def register(parent: click.Group) -> None:
    @parent.group("lead-intel")
    @click.pass_context
    def lead_intel(ctx: click.Context) -> None:
        """End-to-end lead intelligence testing (FUB webhooks, intel docs, scoring, safe vs hands-on)."""
        if ctx.parent is not None and isinstance(ctx.parent.obj, dict):
            ctx.obj = ctx.parent.obj
        else:
            ctx.ensure_object(dict)

    @lead_intel.command("guide")
    def lead_intel_guide() -> None:
        """Print a concise playbook for iterative FUB + workflow testing."""
        click.echo(
            """
Lead intelligence — iterative E2E playbook
===========================================
Run commands from the repository ``backend/`` folder: ``python -m cli.acs …``
(If your shell has an ``acs`` entrypoint, use that instead.)

1) Login
   python -m cli.acs auth login --base-url https://YOUR_GATEWAY --email ... --password ... \\
       --firebase-api-key YOUR_WEB_API_KEY

2) Confirm FUB is connected
   python -m cli.acs integration status

3) Choose safe vs hands-on (controls CRM notes from enrichment / intel-delta)
   Safe (default):   python -m cli.acs lead-intel profile-mode --safe
   Hands-on:         python -m cli.acs lead-intel profile-mode --hands-on
   (Sets Realtors/{uid}.guardrailLevel — same flag integration uses for execution_policy.)

4) Create a person in FUB (triggers real peopleCreated webhook if webhooks are registered)
   python -m cli.acs fub people create --first "Intel" --last "Probe" --email you+probe@example.com

   Or simulate the pipeline without waiting for FUB delivery:
   python -m cli.acs integration webhook --event peopleCreated --person-id 12345678

5) Wait for async work (webhook → core); poll intel + score
   python -m cli.acs lead-intel wait --seconds 8
   python -m cli.acs lead-intel inspect --person-id 12345678

6) Trigger intel delta + re-score (material fields: name / emails / phones)
   python -m cli.acs fub people update --id 12345678 --last "Probe-2"
   # or:
   python -m cli.acs integration webhook --event peopleUpdated --person-id 12345678
   python -m cli.acs lead-intel wait --seconds 8
   python -m cli.acs lead-intel inspect --person-id 12345678

   One-liner to bump lastName for a delta (FUB API → your real webhooks fire):
   python -m cli.acs lead-intel touch-name --id 12345678

7) Read workflow audit from a webhook_test response
   Field ``workflow_debug`` includes core status, ``metadata.execution_policy``, node-ish summary,
   and ``outbound_actions_count`` (webhook_test only).

Related
-------
- Bundle script (raw JSON + optional core POST): integration/functions/bundle/scripts/simulate_fub_webhook_pipeline.py
- Core run (manual state): python -m cli.acs core run --workflow contact.enrichment_v1 --uid UID --payload '{...}' [--volatile]
""".strip()
        )

    @lead_intel.command("wait")
    @click.option("--seconds", default=5, show_default=True, type=float, help="Sleep before the next command.")
    def lead_intel_wait(seconds: float) -> None:
        """Simple pause between FUB writes and inspection (webhooks are not synchronous)."""
        if seconds > 0:
            click.echo(click.style(f"Waiting {seconds}s…", fg="cyan"))
            time.sleep(seconds)

    @lead_intel.command("paths")
    @click.option("--uid", default=None, help="Realtor UID (default: logged-in UID).")
    @click.option("--person-id", "person_id", required=True, type=int, help="FUB person id.")
    def lead_intel_paths(uid: Optional[str], person_id: int) -> None:
        """Print Firestore paths for InternalClients intel + Leads score doc."""
        u = (uid or "").strip() or _uid_from_session()
        ic = internal_client_doc_id(provider="followupboss", external_person_id=str(int(person_id)))
        lead = canonical_lead_doc_id(person_id)
        click.echo(f"Realtors/{u}/InternalClients/{ic}")
        click.echo(f"Realtors/{u}/Leads/{lead}")

    @lead_intel.command("inspect")
    @click.option("--uid", default=None, help="Realtor UID (default: logged-in UID).")
    @click.option("--person-id", "person_id", required=True, type=int, help="FUB person id.")
    @click.pass_context
    def lead_intel_inspect(ctx: click.Context, uid: Optional[str], person_id: int) -> None:
        """Read InternalClients acsIntel + Leads glyde score for one person."""
        u = (uid or "").strip() or _uid_from_session()
        ic = internal_client_doc_id(provider="followupboss", external_person_id=str(int(person_id)))
        lead = canonical_lead_doc_id(person_id)
        bu = ctx.obj.get("base_url") if isinstance(ctx.obj, dict) else None
        try:
            st1, b1 = request("POST", "/db/read", json={"path": f"Realtors/{u}/InternalClients/{ic}"}, base_url_override=bu)
            st2, b2 = request("POST", "/db/read", json={"path": f"Realtors/{u}/Leads/{lead}"}, base_url_override=bu)
        except CliError as e:
            _err(str(e))
        click.echo(click.style("— InternalClients / acsIntel —", fg="cyan", bold=True))
        _out(ctx, st1, b1)
        click.echo(click.style("— Leads / scoring —", fg="cyan", bold=True))
        _out(ctx, st2, b2)

    @lead_intel.command("profile-mode")
    @click.option("--safe", "mode_safe", is_flag=True, help="Analytical mode: volatile_external_allowed=false.")
    @click.option("--hands-on", "mode_hands", is_flag=True, help="Hands-on: allow outbound CRM actions from workflows.")
    @click.pass_context
    def lead_intel_profile_mode(ctx: click.Context, mode_safe: bool, mode_hands: bool) -> None:
        """Set guardrailLevel on the logged-in realtor (matches integration webhook execution policy)."""
        if mode_safe == mode_hands:
            _err("Specify exactly one of --safe or --hands-on.")
        uid = _uid_from_session()
        level = 0 if mode_safe else 1
        bu = ctx.obj.get("base_url") if isinstance(ctx.obj, dict) else None
        path = f"Realtors/{uid}"
        try:
            st, body = request("POST", "/db/read", json={"path": path}, base_url_override=bu)
        except CliError as e:
            _err(str(e))
        if st >= 400:
            _out(ctx, st, body)
        data = body.get("data") if isinstance(body.get("data"), dict) else {}
        merged = {**data, "guardrailLevel": level}
        try:
            st2, body2 = request(
                "POST",
                "/db/upsert",
                json={"path": path, "data": merged, "merge": True},
                base_url_override=bu,
            )
        except CliError as e:
            _err(str(e))
        click.echo(click.style(f"guardrailLevel set to {level}", fg="green"))
        _out(ctx, st2, body2)

    @lead_intel.command("webhook")
    @click.option("--event", required=True, help='peopleCreated | peopleUpdated (aliases: personCreated, …).')
    @click.option("--person-id", "person_id", required=True, type=int, help="FUB person id (resourceIds / uri).")
    @click.option("--event-id", default=None, help="Optional stable eventId (default: random cli-…).")
    @click.option("--workflow-id", default=None, help="Pin a single workflow (default: use production map).")
    @click.pass_context
    def lead_intel_webhook(
        ctx: click.Context,
        event: str,
        person_id: int,
        event_id: Optional[str],
        workflow_id: Optional[str],
    ) -> None:
        """POST webhook_test with a valid FUB-shaped people* body (includes ``event`` field)."""
        canon = normalize_fub_webhook_event(event)
        payload = fub_webhook_minimal_body(event=canon, person_id=person_id, event_id=event_id)
        url = "/integrations/followupboss/webhook_test"
        if workflow_id:
            url += f"?workflowId={workflow_id.strip()}"
        bu = ctx.obj.get("base_url") if isinstance(ctx.obj, dict) else None
        try:
            status, body = request(
                "POST",
                url,
                json=payload,
                headers={"X-FUB-Event": canon},
                base_url_override=bu,
                timeout=120,
            )
        except CliError as e:
            _err(str(e))
        _out(ctx, status, body)

    @lead_intel.command("touch-name")
    @click.option("--id", "person_id", required=True, type=int, help="FUB person id.")
    @click.pass_context
    def lead_intel_touch_name(ctx: click.Context, person_id: int) -> None:
        """Append a random suffix to lastName to trigger intel_delta material diff (then webhook from FUB)."""
        suffix = uuid.uuid4().hex[:6]
        bu = ctx.obj.get("base_url") if isinstance(ctx.obj, dict) else None
        try:
            st, body = request(
                "POST",
                "/integrations/followupboss/people/get",
                json={"personId": person_id},
                base_url_override=bu,
            )
        except CliError as e:
            _err(str(e))
        if st >= 400 or not isinstance(body, dict):
            _out(ctx, st, body)
        last = str(body.get("lastName") or "Lead")
        new_last = f"{last}-acs{suffix}"
        try:
            st2, body2 = request(
                "POST",
                "/integrations/followupboss/people/update",
                json={"personId": person_id, "lastName": new_last},
                base_url_override=bu,
            )
        except CliError as e:
            _err(str(e))
        click.echo(click.style(f"lastName -> {new_last!r}", fg="cyan"))
        _out(ctx, st2, body2)

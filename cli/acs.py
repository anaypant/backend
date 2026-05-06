#!/usr/bin/env python3
"""
acs — ACS Backend CLI

An AI-agent-friendly command-line interface to authenticate against and
exercise every deployed feature of the ACS backend.

Quick start (from ``backend/`` directory):
  pip install -r cli/requirements.txt
  python -m cli.acs auth login --base-url https://acs-public-9l1ydz27.uc.gateway.dev \\
      --email you@example.com --password secret --firebase-api-key AIza...
  python -m cli.acs health
  python -m cli.acs core catalog
  python -m cli.acs lead-intel guide
"""
from __future__ import annotations

import json
import sys
import time
import uuid
from typing import Any, Optional

import click
import requests as _requests

from . import config
from .client import CliError, request
from .lead_intel import register as register_lead_intel
from .lead_intel_helpers import fub_webhook_minimal_body, normalize_fub_webhook_event


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _out(status: int, body: Any, *, raw: bool) -> None:
    """Print result and exit non-zero on HTTP error."""
    if raw:
        if isinstance(body, (dict, list)):
            click.echo(json.dumps(body))
        else:
            click.echo(str(body))
    else:
        prefix = click.style(f"HTTP {status}", fg="green" if status < 400 else "red", bold=True)
        if isinstance(body, (dict, list)):
            click.echo(f"{prefix}\n{json.dumps(body, indent=2)}")
        else:
            click.echo(f"{prefix}\n{body}")
    if status >= 400:
        sys.exit(1)


def _err(msg: str) -> None:
    click.echo(click.style(f"error: {msg}", fg="red"), err=True)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Root group
# ---------------------------------------------------------------------------

@click.group()
@click.option("--base-url", envvar="ACS_API_URL", default=None, help="Override ACS gateway base URL.")
@click.option("--raw", is_flag=True, default=False, help="Print raw JSON without prefix or formatting.")
@click.pass_context
def cli(ctx: click.Context, base_url: Optional[str], raw: bool) -> None:
    """ACS Backend CLI — authenticate and exercise every ACS service endpoint."""
    ctx.ensure_object(dict)
    ctx.obj["base_url"] = base_url
    ctx.obj["raw"] = raw


# ---------------------------------------------------------------------------
# auth
# ---------------------------------------------------------------------------

@cli.group()
def auth() -> None:
    """Login, logout, and inspect the current session."""


@auth.command("login")
@click.option("--base-url", default=None, help="ACS gateway URL (e.g. https://acs-public-....uc.gateway.dev).")
@click.option("--email", default=None, help="Email for password-based login.")
@click.option("--password", default=None, help="Password for password-based login.")
@click.option("--google-token", default=None, help="Google ID token for Google Sign-In login.")
@click.option("--role", default="realtor", type=click.Choice(["realtor", "internal"]),
              show_default=True, help="Auth role to use (realtor or internal).")
@click.option("--firebase-api-key", envvar="FIREBASE_WEB_API_KEY", default=None,
              help="Firebase Web API key (for token refresh). Falls back to FIREBASE_WEB_API_KEY env var.")
@click.pass_context
def auth_login(
    ctx: click.Context,
    base_url: Optional[str],
    email: Optional[str],
    password: Optional[str],
    google_token: Optional[str],
    role: str,
    firebase_api_key: Optional[str],
) -> None:
    """Authenticate against ACS and save a session to ~/.acs-cli/session.json."""
    resolved_base = base_url or ctx.obj.get("base_url") or config.get_base_url()

    if not google_token and (not email or not password):
        _err("Provide either --email + --password, or --google-token.")

    api_key = config.get_firebase_api_key(firebase_api_key)
    if not api_key:
        _err(
            "Firebase API key is required for token refresh.\n"
            "Pass --firebase-api-key or set FIREBASE_WEB_API_KEY."
        )

    body: dict
    if google_token:
        body = {"googleIdToken": google_token}
    else:
        body = {"email": email, "password": password}

    try:
        status, data = request(
            "POST",
            f"/auth/{role}/login",
            json=body,
            auth=False,
            base_url_override=resolved_base,
        )
    except CliError as e:
        _err(str(e))

    if status != 200 or not isinstance(data, dict):
        _out(status, data, raw=ctx.obj["raw"])
        return

    id_token = data.get("idToken", "")
    refresh_token = data.get("refreshToken", "")
    expires_in = int(data.get("expiresIn", 3600))

    if not id_token:
        _err(f"Login succeeded (HTTP {status}) but response contained no idToken: {data}")

    config.save_session(
        base_url=resolved_base,
        id_token=id_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
        firebase_api_key=api_key,
    )

    # Decode UID from JWT payload (no verification — display only)
    uid = config.get_session().get("base_url")  # placeholder — decode below
    try:
        import base64
        parts = id_token.split(".")
        padded = parts[1] + "=" * (4 - len(parts[1]) % 4)
        payload = json.loads(base64.b64decode(padded.replace("-", "+").replace("_", "/")))
        uid = payload.get("user_id") or payload.get("sub") or "unknown"
        role_claim = payload.get("role", "(none)")
        admin_claim = payload.get("admin", False)
    except Exception:
        uid = "unknown"
        role_claim = "unknown"
        admin_claim = False

    click.echo(
        click.style("Logged in.", fg="green", bold=True)
        + f"\n  UID:    {uid}"
        + f"\n  Role:   {role_claim}"
        + f"\n  Admin:  {admin_claim}"
        + f"\n  Expiry: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time() + expires_in))}"
        + f"\n  URL:    {resolved_base}"
    )


@auth.command("status")
def auth_status() -> None:
    """Show the current session (UID, expiry, base URL)."""
    session = config.get_session()
    if not session.get("id_token"):
        click.echo("Not logged in.")
        sys.exit(1)

    expires_at = session.get("expires_at", 0)
    remaining = int(expires_at - time.time())
    expired = remaining <= 0

    try:
        import base64
        parts = session["id_token"].split(".")
        padded = parts[1] + "=" * (4 - len(parts[1]) % 4)
        payload = json.loads(base64.b64decode(padded.replace("-", "+").replace("_", "/")))
        uid = payload.get("user_id") or payload.get("sub") or "unknown"
        role_claim = payload.get("role", "(none)")
        admin_claim = payload.get("admin", False)
    except Exception:
        uid = role_claim = "unknown"
        admin_claim = False

    status_label = click.style("EXPIRED", fg="red") if expired else click.style("valid", fg="green")
    click.echo(
        f"Session:  {status_label}"
        + f"\n  UID:    {uid}"
        + f"\n  Role:   {role_claim}"
        + f"\n  Admin:  {admin_claim}"
        + f"\n  Expiry: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(expires_at))}"
        + (f" (expires in {remaining}s)" if not expired else " (expired)")
        + f"\n  URL:    {session.get('base_url', '(none)')}"
    )


@auth.command("logout")
def auth_logout() -> None:
    """Clear the saved session."""
    config.clear()
    click.echo("Logged out.")


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------

@cli.command("health")
@click.pass_context
def health(ctx: click.Context) -> None:
    """GET /health — unauthenticated gateway liveness check."""
    try:
        status, body = request("GET", "/health", auth=False,
                               base_url_override=ctx.obj.get("base_url"))
    except CliError as e:
        _err(str(e))
    _out(status, body, raw=ctx.obj["raw"])


# ---------------------------------------------------------------------------
# db
# ---------------------------------------------------------------------------

@cli.group()
def db() -> None:
    """Firestore DB operations (read, query, upsert)."""


@db.command("read")
@click.option("--path", required=True, help='Firestore document path, e.g. "Realtors/abc123".')
@click.pass_context
def db_read(ctx: click.Context, path: str) -> None:
    """POST /db/read — read a Firestore document."""
    try:
        status, body = request("POST", "/db/read", json={"path": path},
                               base_url_override=ctx.obj.get("base_url"))
    except CliError as e:
        _err(str(e))
    _out(status, body, raw=ctx.obj["raw"])


@db.command("query")
@click.option("--path", required=True, help='Firestore collection path, e.g. "Realtors".')
@click.option("--filter", "filters", multiple=True, nargs=3,
              metavar="FIELD OP VALUE",
              help='Filter triple, repeatable: --filter ownerUid == abc123')
@click.option("--order", "order_by", multiple=True, nargs=2,
              metavar="FIELD DIRECTION",
              help='Order by: --order createdAt DESC')
@click.option("--limit", default=50, show_default=True, help="Max results.")
@click.option("--page-token", default=None, help="Pagination token from a previous query.")
@click.pass_context
def db_query(
    ctx: click.Context,
    path: str,
    filters: tuple,
    order_by: tuple,
    limit: int,
    page_token: Optional[str],
) -> None:
    """POST /db/query — query a Firestore collection."""
    filter_list = [{"field": f, "op": o, "value": v} for f, o, v in filters]
    order_list = [{"field": f, "direction": d} for f, d in order_by]
    payload: dict = {"path": path, "filters": filter_list, "limit": limit}
    if order_list:
        payload["orderBy"] = order_list
    if page_token:
        payload["pageToken"] = page_token
    try:
        status, body = request("POST", "/db/query", json=payload,
                               base_url_override=ctx.obj.get("base_url"))
    except CliError as e:
        _err(str(e))
    _out(status, body, raw=ctx.obj["raw"])


@db.command("upsert")
@click.option("--path", required=True, help='Firestore document path.')
@click.option("--data", required=True, help='JSON string of fields to write.')
@click.option("--no-merge", is_flag=True, default=False, help="Full overwrite instead of merge.")
@click.pass_context
def db_upsert(ctx: click.Context, path: str, data: str, no_merge: bool) -> None:
    """POST /db/upsert — write fields to a Firestore document."""
    try:
        data_dict = json.loads(data)
    except json.JSONDecodeError as e:
        _err(f"--data is not valid JSON: {e}")
    try:
        status, body = request(
            "POST", "/db/upsert",
            json={"path": path, "data": data_dict, "merge": not no_merge},
            base_url_override=ctx.obj.get("base_url"),
        )
    except CliError as e:
        _err(str(e))
    _out(status, body, raw=ctx.obj["raw"])


# ---------------------------------------------------------------------------
# core
# ---------------------------------------------------------------------------

@cli.group()
def core() -> None:
    """Core workflow runner (run workflows, dev-lab tools, catalog)."""


@core.command("run")
@click.option("--workflow", "workflow_id", required=True,
              help='Workflow ID, e.g. "lead.scoring_v1".')
@click.option("--uid", required=True, help="Realtor UID (user_id in state).")
@click.option("--payload", default="{}", show_default=True,
              help="JSON payload merged into the state envelope.")
@click.option("--volatile", is_flag=True, default=False,
              help="Allow volatile external actions (hands-on mode).")
@click.option("--correlation-id", default=None,
              help="Correlation ID (auto-generated if omitted).")
@click.pass_context
def core_run(
    ctx: click.Context,
    workflow_id: str,
    uid: str,
    payload: str,
    volatile: bool,
    correlation_id: Optional[str],
) -> None:
    """POST /core/v1/run — execute a registered Glyde workflow."""
    try:
        payload_dict = json.loads(payload)
    except json.JSONDecodeError as e:
        _err(f"--payload is not valid JSON: {e}")

    cid = correlation_id or f"cli_{uuid.uuid4().hex[:12]}"
    body = {
        "workflow_id": workflow_id,
        "state": {
            "state_version": 1,
            "correlation_id": cid,
            "source": {"provider": "acs_cli", "event_type": "manual_trigger"},
            "user_id": uid,
            "payload": payload_dict,
            "metadata": {
                "execution_policy": {
                    "volatile_external_allowed": volatile,
                    "integration_maintenance_allowed": True,
                }
            },
        },
    }
    try:
        status, resp = request("POST", "/core/v1/run", json=body,
                               base_url_override=ctx.obj.get("base_url"), timeout=120)
    except CliError as e:
        _err(str(e))
    _out(status, resp, raw=ctx.obj["raw"])


@core.command("catalog")
@click.pass_context
def core_catalog(ctx: click.Context) -> None:
    """List registered workflows and tools via dev-lab (requires ACS_ENABLE_DEV_LAB=1)."""
    try:
        status, body = request(
            "POST", "/core/v1/run",
            json={"__ACS_DEV_LAB__": "catalog", "acting_uid": "cli"},
            base_url_override=ctx.obj.get("base_url"),
        )
    except CliError as e:
        _err(str(e))
    _out(status, body, raw=ctx.obj["raw"])


@core.command("tool")
@click.option("--id", "tool_id", required=True, help='Tool ID, e.g. "db.merge_realtor_profile".')
@click.option("--args", default="{}", show_default=True, help="JSON args dict for the tool.")
@click.option("--uid", required=True, help="Acting UID.")
@click.option("--volatile", is_flag=True, default=False, help="Allow volatile tool execution.")
@click.pass_context
def core_tool(ctx: click.Context, tool_id: str, args: str, uid: str, volatile: bool) -> None:
    """Run a single registered tool via dev-lab (requires ACS_ENABLE_DEV_LAB=1)."""
    try:
        args_dict = json.loads(args)
    except json.JSONDecodeError as e:
        _err(f"--args is not valid JSON: {e}")
    acs_policy = {"execution_policy": {"volatile_external_allowed": volatile}} if volatile else None
    body: dict = {
        "__ACS_DEV_LAB__": "run_tool",
        "tool_id": tool_id,
        "args": args_dict,
        "acting_uid": uid,
    }
    if acs_policy:
        body["acs"] = acs_policy
    try:
        status, resp = request("POST", "/core/v1/run", json=body,
                               base_url_override=ctx.obj.get("base_url"), timeout=60)
    except CliError as e:
        _err(str(e))
    _out(status, resp, raw=ctx.obj["raw"])


@core.command("checks")
@click.option("--uid", required=True, help="Acting UID (required by dev-lab, not used for auth).")
@click.pass_context
def core_checks(ctx: click.Context, uid: str) -> None:
    """Run core unit checks via dev-lab (requires ACS_ENABLE_DEV_LAB=1)."""
    try:
        status, body = request(
            "POST", "/core/v1/run",
            json={"__ACS_DEV_LAB__": "run_unit_checks", "acting_uid": uid},
            base_url_override=ctx.obj.get("base_url"),
        )
    except CliError as e:
        _err(str(e))
    _out(status, body, raw=ctx.obj["raw"])


# ---------------------------------------------------------------------------
# integration
# ---------------------------------------------------------------------------

@cli.group()
def integration() -> None:
    """FollowUpBoss integration commands."""


@integration.command("status")
@click.pass_context
def integration_status(ctx: click.Context) -> None:
    """GET /integrations/followupboss/status — FUB connection status."""
    try:
        status, body = request("GET", "/integrations/followupboss/status",
                               base_url_override=ctx.obj.get("base_url"))
    except CliError as e:
        _err(str(e))
    _out(status, body, raw=ctx.obj["raw"])


@integration.command("unit-checks")
@click.pass_context
def integration_unit_checks(ctx: click.Context) -> None:
    """POST /integrations/followupboss/qa/unit_checks — deterministic mapping checks (no live FUB API)."""
    try:
        status, body = request("POST", "/integrations/followupboss/qa/unit_checks", json={},
                               base_url_override=ctx.obj.get("base_url"))
    except CliError as e:
        _err(str(e))
    _out(status, body, raw=ctx.obj["raw"])


@integration.command("webhook")
@click.option("--event", required=True,
              help='FUB event: peopleCreated, peopleUpdated, noteCreated, … (aliases: personCreated → peopleCreated).')
@click.option("--person-id", "person_id", default=None, type=int,
              help="For people* events without --payload: build minimal uri/resourceIds body (default: 1).")
@click.option("--payload", default=None,
              help="JSON event payload. Defaults to a minimal stub for the event type.")
@click.option("--workflow-id", default=None,
              help="Pin execution to a specific workflow ID (optional).")
@click.pass_context
def integration_webhook(
    ctx: click.Context,
    event: str,
    person_id: Optional[int],
    payload: Optional[str],
    workflow_id: Optional[str],
) -> None:
    """POST /integrations/followupboss/webhook_test — simulate a FUB webhook event."""
    canon = normalize_fub_webhook_event(event)

    if payload:
        try:
            payload_dict = json.loads(payload)
        except json.JSONDecodeError as e:
            _err(f"--payload is not valid JSON: {e}")
        if isinstance(payload_dict, dict) and "event" not in payload_dict:
            payload_dict = dict(payload_dict)
            payload_dict["event"] = canon
    elif canon in ("peopleCreated", "peopleUpdated"):
        pid = int(person_id) if person_id is not None else 1
        payload_dict = fub_webhook_minimal_body(event=canon, person_id=pid)
    else:
        _DEFAULT_PAYLOADS: dict[str, dict] = {
            "noteCreated": {"event": "noteCreated", "note": {"id": 101, "body": "Called — interested in listings.", "personId": 1}},
            "taskCreated": {"event": "taskCreated", "task": {"id": 201, "name": "Follow up call", "dueDate": "2026-05-01", "personId": 1}},
            "appointmentCreated": {
                "event": "appointmentCreated",
                "appointment": {"id": 301, "title": "Property showing", "startTime": "2026-05-02T14:00:00Z", "personId": 1},
            },
        }
        payload_dict = _DEFAULT_PAYLOADS.get(canon)
        if payload_dict is None:
            payload_dict = {"event": canon, "event_type": canon}

    url = "/integrations/followupboss/webhook_test"
    if workflow_id:
        url += f"?workflowId={workflow_id}"

    try:
        status, body = request(
            "POST", url,
            json=payload_dict,
            headers={"X-FUB-Event": canon},
            base_url_override=ctx.obj.get("base_url"),
            timeout=120,
        )
    except CliError as e:
        _err(str(e))
    _out(status, body, raw=ctx.obj["raw"])


@integration.command("resync-webhooks")
@click.pass_context
def integration_resync(ctx: click.Context) -> None:
    """POST /integrations/followupboss/resync_webhooks — re-register FUB webhooks for the authed user."""
    try:
        status, body = request("POST", "/integrations/followupboss/resync_webhooks", json={},
                               base_url_override=ctx.obj.get("base_url"))
    except CliError as e:
        _err(str(e))
    _out(status, body, raw=ctx.obj["raw"])


# ---------------------------------------------------------------------------
# fub  (Follow Up Boss direct operations)
# ---------------------------------------------------------------------------

@cli.group()
def fub() -> None:
    """Follow Up Boss — people, notes, tasks, tags, token refresh, import, webhooks."""


# ── fub people ───────────────────────────────────────────────────────────────

@fub.group("people")
def fub_people() -> None:
    """People CRUD operations in Follow Up Boss."""


@fub_people.command("list")
@click.option("--limit", default=50, show_default=True, help="Max people per page (1-100).")
@click.option("--offset", default=0, show_default=True, help="Pagination offset.")
@click.option("--next", "next_token", default=None, help="Cursor token from a previous response.")
@click.pass_context
def fub_people_list(ctx: click.Context, limit: int, offset: int, next_token: Optional[str]) -> None:
    """List people from FUB (paginated)."""
    body: dict = {"limit": limit}
    if next_token:
        body["next"] = next_token
    else:
        body["offset"] = offset
    try:
        status, resp = request("POST", "/integrations/followupboss/people/list", json=body,
                               base_url_override=ctx.obj.get("base_url"))
    except CliError as e:
        _err(str(e))
    _out(status, resp, raw=ctx.obj["raw"])


@fub_people.command("get")
@click.option("--id", "person_id", required=True, type=int, help="FUB person ID.")
@click.pass_context
def fub_people_get(ctx: click.Context, person_id: int) -> None:
    """Fetch a single FUB person by ID."""
    try:
        status, resp = request("POST", "/integrations/followupboss/people/get",
                               json={"personId": person_id},
                               base_url_override=ctx.obj.get("base_url"))
    except CliError as e:
        _err(str(e))
    _out(status, resp, raw=ctx.obj["raw"])


@fub_people.command("create")
@click.option("--first", default=None, help="First name.")
@click.option("--last", default=None, help="Last name.")
@click.option("--email", "emails", multiple=True, help="Email address (repeatable).")
@click.option("--phone", "phones", multiple=True, help="Phone number (repeatable).")
@click.option("--stage", default=None, help='Pipeline stage, e.g. "New Lead", "Active Buyer".')
@click.option("--source", default=None, help='Lead source, e.g. "Referral", "Zillow".')
@click.option("--price", default=None, type=int, help="Budget/price point in dollars.")
@click.option("--tag", "tags", multiple=True, help="Tag name (repeatable).")
@click.pass_context
def fub_people_create(
    ctx: click.Context,
    first: Optional[str],
    last: Optional[str],
    emails: tuple,
    phones: tuple,
    stage: Optional[str],
    source: Optional[str],
    price: Optional[int],
    tags: tuple,
) -> None:
    """Create (or merge) a person in FUB."""
    if not first and not emails:
        _err("Provide --first or at least one --email.")
    body: dict = {}
    if first:
        body["firstName"] = first
    if last:
        body["lastName"] = last
    if emails:
        body["emails"] = [{"value": e} for e in emails]
    if phones:
        body["phones"] = [{"value": p} for p in phones]
    if stage:
        body["stage"] = stage
    if source:
        body["source"] = source
    if price is not None:
        body["price"] = price
    if tags:
        body["tags"] = list(tags)
    try:
        status, resp = request("POST", "/integrations/followupboss/people/create", json=body,
                               base_url_override=ctx.obj.get("base_url"))
    except CliError as e:
        _err(str(e))
    _out(status, resp, raw=ctx.obj["raw"])


@fub_people.command("update")
@click.option("--id", "person_id", required=True, type=int, help="FUB person ID.")
@click.option("--first", default=None, help="First name.")
@click.option("--last", default=None, help="Last name.")
@click.option("--email", "emails", multiple=True, help="Email address (replaces all; repeatable).")
@click.option("--phone", "phones", multiple=True, help="Phone number (replaces all; repeatable).")
@click.option("--stage", default=None, help="Pipeline stage.")
@click.option("--source", default=None, help="Lead source.")
@click.option("--price", default=None, type=int, help="Budget/price point.")
@click.pass_context
def fub_people_update(
    ctx: click.Context,
    person_id: int,
    first: Optional[str],
    last: Optional[str],
    emails: tuple,
    phones: tuple,
    stage: Optional[str],
    source: Optional[str],
    price: Optional[int],
) -> None:
    """Update fields on an existing FUB person."""
    body: dict = {"personId": person_id}
    if first:
        body["firstName"] = first
    if last:
        body["lastName"] = last
    if emails:
        body["emails"] = [{"value": e} for e in emails]
    if phones:
        body["phones"] = [{"value": p} for p in phones]
    if stage:
        body["stage"] = stage
    if source:
        body["source"] = source
    if price is not None:
        body["price"] = price
    if len(body) == 1:
        _err("Provide at least one field to update.")
    try:
        status, resp = request("POST", "/integrations/followupboss/people/update", json=body,
                               base_url_override=ctx.obj.get("base_url"))
    except CliError as e:
        _err(str(e))
    _out(status, resp, raw=ctx.obj["raw"])


@fub_people.command("stage")
@click.option("--id", "person_id", required=True, type=int, help="FUB person ID.")
@click.option("--stage", required=True, help='New stage name, e.g. "Active Buyer", "Under Contract".')
@click.pass_context
def fub_people_stage(ctx: click.Context, person_id: int, stage: str) -> None:
    """Set the pipeline stage for a FUB person."""
    try:
        status, resp = request("POST", "/integrations/followupboss/people/stage",
                               json={"personId": person_id, "stage": stage},
                               base_url_override=ctx.obj.get("base_url"))
    except CliError as e:
        _err(str(e))
    _out(status, resp, raw=ctx.obj["raw"])


# ── fub tags ─────────────────────────────────────────────────────────────────

@fub.group("tags")
def fub_tags() -> None:
    """Add or remove tags on a FUB person (non-destructive merge/filter)."""


@fub_tags.command("add")
@click.option("--id", "person_id", required=True, type=int, help="FUB person ID.")
@click.option("--tag", "tags", required=True, multiple=True, help="Tag name to add (repeatable).")
@click.pass_context
def fub_tags_add(ctx: click.Context, person_id: int, tags: tuple) -> None:
    """Add one or more tags to a FUB person (existing tags are preserved)."""
    try:
        status, resp = request("POST", "/integrations/followupboss/people/tags/add",
                               json={"personId": person_id, "tags": list(tags)},
                               base_url_override=ctx.obj.get("base_url"))
    except CliError as e:
        _err(str(e))
    _out(status, resp, raw=ctx.obj["raw"])


@fub_tags.command("remove")
@click.option("--id", "person_id", required=True, type=int, help="FUB person ID.")
@click.option("--tag", "tags", required=True, multiple=True, help="Tag name to remove (repeatable).")
@click.pass_context
def fub_tags_remove(ctx: click.Context, person_id: int, tags: tuple) -> None:
    """Remove one or more tags from a FUB person (other tags are preserved)."""
    try:
        status, resp = request("POST", "/integrations/followupboss/people/tags/remove",
                               json={"personId": person_id, "tags": list(tags)},
                               base_url_override=ctx.obj.get("base_url"))
    except CliError as e:
        _err(str(e))
    _out(status, resp, raw=ctx.obj["raw"])


# ── fub notes ────────────────────────────────────────────────────────────────

@fub.group("notes")
def fub_notes() -> None:
    """Create notes on a FUB person."""


@fub_notes.command("create")
@click.option("--id", "person_id", required=True, type=int, help="FUB person ID.")
@click.option("--body", "note_body", required=True, help="Note text.")
@click.pass_context
def fub_notes_create(ctx: click.Context, person_id: int, note_body: str) -> None:
    """Add a note to a FUB person."""
    try:
        status, resp = request("POST", "/integrations/followupboss/notes/create",
                               json={"personId": person_id, "body": note_body},
                               base_url_override=ctx.obj.get("base_url"))
    except CliError as e:
        _err(str(e))
    _out(status, resp, raw=ctx.obj["raw"])


@fub_notes.command("list")
@click.option("--id", "person_id", required=True, type=int, help="FUB person ID.")
@click.option("--limit", default=100, show_default=True, type=int, help="Max notes (1–100).")
@click.option("--offset", default=0, show_default=True, type=int, help="Pagination offset.")
@click.pass_context
def fub_notes_list(ctx: click.Context, person_id: int, limit: int, offset: int) -> None:
    """List notes for a FUB person (newest batch via FUB /notes API)."""
    try:
        status, resp = request(
            "POST",
            "/integrations/followupboss/notes/list",
            json={"personId": person_id, "limit": limit, "offset": offset},
            base_url_override=ctx.obj.get("base_url"),
            timeout=60,
        )
    except CliError as e:
        _err(str(e))
    _out(status, resp, raw=ctx.obj["raw"])


# ── fub tasks ────────────────────────────────────────────────────────────────

@fub.group("tasks")
def fub_tasks() -> None:
    """Create tasks on a FUB person."""


@fub_tasks.command("create")
@click.option("--id", "person_id", required=True, type=int, help="FUB person ID.")
@click.option("--body", "task_body", required=True, help="Task description.")
@click.pass_context
def fub_tasks_create(ctx: click.Context, person_id: int, task_body: str) -> None:
    """Create a follow-up task for a FUB person."""
    try:
        status, resp = request("POST", "/integrations/followupboss/tasks/create",
                               json={"personId": person_id, "body": task_body},
                               base_url_override=ctx.obj.get("base_url"))
    except CliError as e:
        _err(str(e))
    _out(status, resp, raw=ctx.obj["raw"])


# ── fub OAuth token ───────────────────────────────────────────────────────────

@fub.command("refresh")
@click.pass_context
def fub_refresh(ctx: click.Context) -> None:
    """Refresh the FUB OAuth access token (use when list/import return expired-access-token)."""
    try:
        status, resp = request(
            "POST",
            "/integrations/followupboss/refresh",
            json={},
            base_url_override=ctx.obj.get("base_url"),
            timeout=60,
        )
    except CliError as e:
        _err(str(e))
    _out(status, resp, raw=ctx.obj["raw"])


# ── fub webhooks ─────────────────────────────────────────────────────────────

@fub.group("webhooks")
def fub_webhooks() -> None:
    """Inspect and manage FUB webhook registrations."""


@fub_webhooks.command("list")
@click.pass_context
def fub_webhooks_list(ctx: click.Context) -> None:
    """List webhooks registered in FUB for this account."""
    try:
        status, resp = request("GET", "/integrations/followupboss/webhooks",
                               base_url_override=ctx.obj.get("base_url"))
    except CliError as e:
        _err(str(e))
    _out(status, resp, raw=ctx.obj["raw"])


@fub_webhooks.command("resync")
@click.pass_context
def fub_webhooks_resync(ctx: click.Context) -> None:
    """Re-register ACS webhooks in FUB (idempotent — safe to run anytime)."""
    try:
        status, resp = request("POST", "/integrations/followupboss/resync_webhooks", json={},
                               base_url_override=ctx.obj.get("base_url"))
    except CliError as e:
        _err(str(e))
    _out(status, resp, raw=ctx.obj["raw"])


# ── fub import ───────────────────────────────────────────────────────────────

@fub.command("import")
@click.option("--person-id", default=None, type=int,
              help="Refresh a single FUB person into Firestore by ID.")
@click.option("--max-pages", default=None, type=int,
              help="Limit paginated full-sync to N pages (default: all).")
@click.pass_context
def fub_import(ctx: click.Context, person_id: Optional[int], max_pages: Optional[int]) -> None:
    """Sync FUB people into Firestore (single person or full account sync)."""
    body: dict = {}
    if person_id is not None:
        body["personId"] = person_id
    if max_pages is not None:
        body["maxPages"] = max_pages
    try:
        status, resp = request("POST", "/integrations/followupboss/import", json=body,
                               base_url_override=ctx.obj.get("base_url"), timeout=300)
    except CliError as e:
        _err(str(e))
    _out(status, resp, raw=ctx.obj["raw"])


@fub.command("import-batch")
@click.option("--batch-size", default=None, type=int, help="FUB people list page size (list mode).")
@click.option("--offset", default=None, type=int, help="FUB list offset (list mode).")
@click.option("--next", "next_token", default=None, type=str, help="FUB pagination cursor (list mode).")
@click.option("--person-id", default=None, type=int, help="Import a single person by FUB id.")
@click.option("--max-list-pages", default=None, type=int, help="Cap list sync pages (list mode).")
@click.pass_context
def fub_import_batch(
    ctx: click.Context,
    batch_size: Optional[int],
    offset: Optional[int],
    next_token: Optional[str],
    person_id: Optional[int],
    max_list_pages: Optional[int],
) -> None:
    """
    One batch via POST /integrations/followupboss/migration/import-batch (integration preflight + core).

    Derives Firebase uid from the CLI session token — no --user-id flag needed.
    """
    session = config.get_session()
    token = session.get("id_token")
    if not token:
        _err("Not logged in. Run `acs auth login` first.")
    try:
        import base64 as _b64

        parts = token.split(".")
        padded = parts[1] + "=" * (4 - len(parts[1]) % 4)
        payload = json.loads(_b64.b64decode(padded.replace("-", "+").replace("_", "/")))
        uid = payload.get("user_id") or payload.get("sub")
    except Exception:
        uid = None
    if not uid:
        _err("Could not read uid from id_token; re-run `acs auth login`.")

    body: dict = {"userId": uid}
    if person_id is not None:
        body["personId"] = person_id
    if batch_size is not None:
        body["batchSize"] = batch_size
    if offset is not None:
        body["offset"] = offset
    if next_token:
        body["next"] = next_token
    if max_list_pages is not None:
        body["maxListPages"] = max_list_pages

    try:
        status, resp = request(
            "POST",
            "/integrations/followupboss/migration/import-batch",
            json=body,
            base_url_override=ctx.obj.get("base_url"),
            timeout=180,
        )
    except CliError as e:
        _err(str(e))
    _out(status, resp, raw=ctx.obj["raw"])


# ---------------------------------------------------------------------------
# admin
# ---------------------------------------------------------------------------

@cli.group()
def admin() -> None:
    """Admin operations (requires admin:true custom claim)."""


@admin.command("promote")
@click.option("--uid", required=True, help="Firebase UID of the user to promote to internal admin.")
@click.pass_context
def admin_promote(ctx: click.Context, uid: str) -> None:
    """POST /auth/internal/promote-admin — grant admin + internal role to a user."""
    try:
        status, body = request(
            "POST", "/auth/internal/promote-admin",
            json={"uid": uid},
            base_url_override=ctx.obj.get("base_url"),
        )
    except CliError as e:
        _err(str(e))
    _out(status, body, raw=ctx.obj["raw"])


# ---------------------------------------------------------------------------
# Convenience: `acs whoami` — quick session summary
# ---------------------------------------------------------------------------

@cli.command("whoami")
@click.pass_context
def whoami(ctx: click.Context) -> None:
    """Print the current session identity (alias for `auth status`)."""
    ctx.invoke(auth_status)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

register_lead_intel(cli)


if __name__ == "__main__":
    cli()

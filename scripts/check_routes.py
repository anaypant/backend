#!/usr/bin/env python3
"""
Route parity check for the ACS API gateway layer.

The ACS request chain for integration paths is:

  Client  →  Public gateway (backend/api/gateway.tf)
           →  Internal integration gateway (backend/integration/api/main.tf)
           →  Integration Cloud Function (bridge_function)

Both gateway layers must declare the same integration routes.  When a new
path is added to the public gateway but the internal gateway is left behind
the route returns:

    {"message": "The current request is not defined by this API.", "code": 404}

This script (1) parses both Terraform files and asserts public↔internal
parity for integration traffic, and (2) parses ``public_api.py`` and asserts
every Follow Up Boss route exposed by the integration bundle exists on **both**
gateway layers (so adding a handler without Terraform fails CI / pre-deploy).

Run it before every deploy:

    python backend/scripts/check_routes.py

Exit code 0 = all good.  Exit code 1 = drift detected (details printed).

The public↔internal check only flags paths in the public gateway that route to
the *integration internal base*.  Auth-service, DB-service, and core-runner
paths are irrelevant there.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# ── File locations (relative to backend/) ───────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent  # backend/
PUBLIC_GW = REPO_ROOT / "api" / "gateway.tf"
INTERNAL_GW = REPO_ROOT / "integration" / "api" / "main.tf"
PUBLIC_API = REPO_ROOT / "integration" / "functions" / "bundle" / "routes" / "public_api.py"

# FUB paths in ``public_api.ROUTES`` that are *not* reached through the dual
# public → internal API gateways (direct integration-bridge / worker URL).
FUB_DUAL_GATEWAY_EXCLUDE = frozenset({"/integrations/followupboss/internal/webhook_sync"})
# OAuth callback is on the public gateway but proxies to callback_bridge, not
# ``integration_internal_base`` — do not require it inside ``integration_required``.
FUB_PUBLIC_SPECIAL_PROXY = frozenset({"/integrations/followupboss/oauth/callback"})

# Marker used in the public gateway to identify integration backend entries.
# All x-google-backend address values that contain this fragment are
# integration routes that must also exist in the internal gateway.
INTEGRATION_ADDR_MARKER = "integration_internal_base"


def _extract_paths(tf_text: str) -> set[str]:
    """
    Return all OpenAPI-style path strings declared in a .tf file.
    Matches both:
        "/some/path" = {          (top-level map key)
      and:
        "/some/path" = {          (nested inside a local block)
    """
    return set(re.findall(r'^\s*"(/[^"]+)"\s*=\s*\{', tf_text, re.MULTILINE))


def _integration_paths_from_public_gw(tf_text: str) -> set[str]:
    """
    From the public gateway file, return only the paths whose x-google-backend
    address references the integration internal base.  These are the paths that
    the internal integration gateway must also declare.
    """
    # Split on top-level path blocks.  Each block starts with  "/<path>" = {
    # and ends before the next such block or end-of-file.
    block_re = re.compile(
        r'"(/[^"]+)"\s*=\s*\{(.*?)(?=\n\s*"/|\Z)',
        re.DOTALL,
    )
    integration_paths: set[str] = set()
    for m in block_re.finditer(tf_text):
        path, body = m.group(1), m.group(2)
        if INTEGRATION_ADDR_MARKER in body:
            integration_paths.add(path)
    return integration_paths


def _paths_from_internal_gw(tf_text: str) -> set[str]:
    """
    Return all path strings from the internal integration gateway file.
    """
    return _extract_paths(tf_text)


def _followupboss_paths_from_public_api(py_text: str) -> set[str]:
    """
    Extract ``/integrations/followupboss/...`` path keys from ``public_api.py``
    (string keys in the ROUTES dict).  Excludes routes that bypass the dual gateways.
    """
    found = set(re.findall(r'"(/integrations/followupboss/[^"]+)"\s*:', py_text))
    return found - FUB_DUAL_GATEWAY_EXCLUDE


def run_check() -> int:
    if not PUBLIC_GW.exists():
        print(f"ERROR: public gateway file not found: {PUBLIC_GW}", file=sys.stderr)
        return 1
    if not INTERNAL_GW.exists():
        print(f"ERROR: internal gateway file not found: {INTERNAL_GW}", file=sys.stderr)
        return 1
    if not PUBLIC_API.exists():
        print(f"ERROR: integration public_api.py not found: {PUBLIC_API}", file=sys.stderr)
        return 1

    public_text = PUBLIC_GW.read_text(encoding="utf-8")
    internal_text = INTERNAL_GW.read_text(encoding="utf-8")
    public_api_text = PUBLIC_API.read_text(encoding="utf-8")

    integration_required = _integration_paths_from_public_gw(public_text)
    internal_declared = _paths_from_internal_gw(internal_text)
    public_all_paths = _extract_paths(public_text)
    fub_from_bundle = _followupboss_paths_from_public_api(public_api_text)

    missing_in_internal = integration_required - internal_declared
    # Internal-only or callback-bridge paths are not in ``integration_required``.
    internal_public_mismatch_ok = (
        frozenset({"/health"})
        | FUB_PUBLIC_SPECIAL_PROXY
        | {
            "/integrations/internal/state/from_providers",
            "/integrations/internal/state/to_providers",
        }
    )
    stale_in_internal = internal_declared - integration_required - internal_public_mismatch_ok

    ok = True

    fub_needs_integration_backend = fub_from_bundle - FUB_PUBLIC_SPECIAL_PROXY
    missing_on_public_for_fub = fub_needs_integration_backend - integration_required
    missing_on_internal_for_fub = fub_from_bundle - internal_declared

    for p in sorted(FUB_PUBLIC_SPECIAL_PROXY & fub_from_bundle):
        if p not in public_all_paths:
            ok = False
            print("=" * 70)
            print(
                "PUBLIC GATEWAY MISSING — OAuth callback route must exist "
                f"(callback_bridge proxy): {p!r}"
            )
            print("=" * 70)
            print()

    if missing_on_public_for_fub:
        ok = False
        print("=" * 70)
        print("PUBLIC GATEWAY MISSING — Follow Up Boss routes in public_api.py")
        print("        but NOT declared in api/gateway.tf (client gets HTTP 404):")
        print("=" * 70)
        for p in sorted(missing_on_public_for_fub):
            print(f"  MISSING  {p}")
        print()
        print("Fix: add each path to backend/api/gateway.tf (integration_proxy_paths),")
        print("     mirroring a nearby POST route (x-google-backend → integration_internal_base).")
        print()

    if missing_on_internal_for_fub:
        ok = False
        print("=" * 70)
        print("INTERNAL GATEWAY MISSING — Follow Up Boss routes in public_api.py")
        print("        but NOT declared in integration/api/main.tf:")
        print("=" * 70)
        for p in sorted(missing_on_internal_for_fub):
            print(f"  MISSING  {p}")
        print()
        print("Fix: add each path to backend/integration/api/main.tf (integration_paths).")
        print()

    if missing_in_internal:
        ok = False
        print("=" * 70)
        print("ROUTE PARITY FAILURE — deploy will be broken for these paths:")
        print("=" * 70)
        print()
        print("Paths present in PUBLIC gateway (api/gateway.tf)")
        print("but MISSING from INTERNAL integration gateway (integration/api/main.tf):")
        print()
        for p in sorted(missing_in_internal):
            print(f"  MISSING  {p}")
        print()
        print("Fix: add each missing path to integration/api/main.tf")
        print("     following the same pattern as nearby routes (POST, security=[],")
        print("     'x-google-backend' = local.integration_backend).")
        print()

    if stale_in_internal:
        # Warn but don't fail — extra routes in internal are harmless (they just
        # never receive traffic from the public layer).
        print("WARNING — stale routes in internal gateway (no traffic, harmless):")
        for p in sorted(stale_in_internal):
            print(f"  STALE    {p}")
        print()

    if ok:
        print(f"OK — {len(integration_required)} integration routes in public↔internal parity.")
        print(f"     OK — {len(fub_from_bundle)} Follow Up Boss bundle routes on both gateways.")
        print(f"     Public gateway  : {PUBLIC_GW.relative_to(REPO_ROOT.parent)}")
        print(f"     Internal gateway: {INTERNAL_GW.relative_to(REPO_ROOT.parent)}")
        print(f"     Bundle ROUTES   : {PUBLIC_API.relative_to(REPO_ROOT.parent)}")
    else:
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(run_check())

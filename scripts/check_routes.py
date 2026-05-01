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

This script parses both Terraform files, extracts the declared paths, and
asserts they are in sync.  Run it before every deploy:

    python backend/scripts/check_routes.py

Exit code 0 = all good.  Exit code 1 = drift detected (details printed).

The check is conservative: it only flags paths in the public gateway that
route to the *integration internal base* (i.e. integration service paths).
Auth-service, DB-service, and core-runner paths are irrelevant here.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# ── File locations (relative to backend/) ───────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent  # backend/
PUBLIC_GW = REPO_ROOT / "api" / "gateway.tf"
INTERNAL_GW = REPO_ROOT / "integration" / "api" / "main.tf"

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


def run_check() -> int:
    if not PUBLIC_GW.exists():
        print(f"ERROR: public gateway file not found: {PUBLIC_GW}", file=sys.stderr)
        return 1
    if not INTERNAL_GW.exists():
        print(f"ERROR: internal gateway file not found: {INTERNAL_GW}", file=sys.stderr)
        return 1

    public_text = PUBLIC_GW.read_text(encoding="utf-8")
    internal_text = INTERNAL_GW.read_text(encoding="utf-8")

    integration_required = _integration_paths_from_public_gw(public_text)
    internal_declared = _paths_from_internal_gw(internal_text)

    missing_in_internal = integration_required - internal_declared
    # Paths in internal gateway that no longer exist in public (stale but harmless)
    stale_in_internal = internal_declared - integration_required - {"/health"}

    ok = True

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
        print(f"OK — {len(integration_required)} integration routes in parity.")
        print(f"     Public gateway  : {PUBLIC_GW.relative_to(REPO_ROOT.parent)}")
        print(f"     Internal gateway: {INTERNAL_GW.relative_to(REPO_ROOT.parent)}")
    else:
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(run_check())

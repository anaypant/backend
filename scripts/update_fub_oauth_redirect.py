#!/usr/bin/env python3
"""
Register the ACS public gateway OAuth callback on your Follow Up Boss OAuth app.

FUB validates redirect_uri against this list. Callback path must match integration-bridge:
  {ACS_PUBLIC_INTEGRATION_BASE_URL}/integrations/followupboss/oauth/callback

Usage:
  1. Set the variables below OR export FUB_X_SYSTEM, FUB_X_SYSTEM_KEY (recommended for secrets).
  2. python backend/scripts/update_fub_oauth_redirect.py

Optional:
  FUB_EXTRA_REDIRECT_URIS — comma-separated full URLs to add alongside the default callback.
"""

from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.error
import urllib.request

# ---------------------------------------------------------------------------
# Fill in before running (secrets: prefer environment variables instead).
# ---------------------------------------------------------------------------
FUB_X_SYSTEM = "acs-dev"
FUB_X_SYSTEM_KEY = "2b615f84728548771e7b4dd45277852e"

# Public API origin (no trailing slash). Must match deployed ACS_PUBLIC_INTEGRATION_BASE_URL.
ACS_PUBLIC_INTEGRATION_BASE_URL = "https://acs-public-9l1ydz27.uc.gateway.dev"

FUB_OAUTH_APPS_URL = "https://api.followupboss.com/v1/oauthApps"
OAUTH_CALLBACK_PATH = "/integrations/followupboss/oauth/callback"


def _env(name: str, default: str = "") -> str:
    v = os.environ.get(name)
    if v is not None and str(v).strip():
        return str(v).strip()
    return default.strip()


def _callback_urls() -> list[str]:
    base = _env("ACS_PUBLIC_INTEGRATION_BASE_URL", ACS_PUBLIC_INTEGRATION_BASE_URL).rstrip("/")
    primary = f"{base}{OAUTH_CALLBACK_PATH}"
    extra = _env("FUB_EXTRA_REDIRECT_URIS", "")
    out = [primary]
    for part in extra.split(","):
        u = part.strip()
        if u and u not in out:
            out.append(u)
    return out


def main() -> int:
    x_system = _env("FUB_X_SYSTEM", FUB_X_SYSTEM)
    x_key = _env("FUB_X_SYSTEM_KEY", FUB_X_SYSTEM_KEY)
    if not x_system or not x_key:
        print(
            "Missing FUB_X_SYSTEM or FUB_X_SYSTEM_KEY.\n"
            "Set them in this file or export:\n"
            "  export FUB_X_SYSTEM=...\n"
            "  export FUB_X_SYSTEM_KEY=...",
            file=sys.stderr,
        )
        return 1

    redirect_uris = _callback_urls()
    body = json.dumps({"redirectUris": redirect_uris}).encode("utf-8")
    req = urllib.request.Request(
        FUB_OAUTH_APPS_URL,
        data=body,
        method="PUT",
        headers={
            "X-System": x_system,
            "X-System-Key": x_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )

    print(f"PUT {FUB_OAUTH_APPS_URL}")
    print(f"redirectUris: {json.dumps(redirect_uris, indent=2)}")

    try:
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            print(f"Status: {resp.status}")
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        print(f"HTTP {e.code}: {err_body}", file=sys.stderr)
        return 1

    print(raw)
    try:
        data = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return 0

    if isinstance(data, dict) and data.get("redirectUris"):
        print("\nRegistered redirect URIs:", data.get("redirectUris"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""
Propagate the canonical acs_internal.py to all service bundle copies.

Usage:
    python backend/scripts/sync_acs_internal.py [--dry-run]

This overwrites all copies listed in check_acs_internal_sync.py with the canonical version.
Run check_acs_internal_sync.py afterwards to verify.
"""

from __future__ import annotations

import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

CANONICAL = REPO_ROOT / "backend" / "integration" / "functions" / "bundle" / "acs_internal.py"

COPIES: list[pathlib.Path] = [
    REPO_ROOT / "backend" / "auth" / "functions" / "bundle" / "acs_internal.py",
    REPO_ROOT / "backend" / "core" / "functions" / "runner" / "acs_internal.py",
    REPO_ROOT / "backend" / "db" / "functions" / "delete" / "acs_internal.py",
    REPO_ROOT / "backend" / "db" / "functions" / "query" / "acs_internal.py",
    REPO_ROOT / "backend" / "db" / "functions" / "read" / "acs_internal.py",
    REPO_ROOT / "backend" / "db" / "functions" / "upsert" / "acs_internal.py",
    REPO_ROOT / "backend" / "integration" / "functions" / "bundle" / "acs_internal.py",
]

DRY_RUN = "--dry-run" in sys.argv


def main() -> int:
    if not CANONICAL.exists():
        print(f"ERROR: canonical not found: {CANONICAL.relative_to(REPO_ROOT)}")
        return 1

    canonical_text = CANONICAL.read_text(encoding="utf-8")
    print(f"Canonical: {CANONICAL.relative_to(REPO_ROOT)}")
    if DRY_RUN:
        print("(dry-run mode — no files written)\n")

    updated = 0
    skipped = 0
    for copy in COPIES:
        if copy == CANONICAL:
            continue
        rel = copy.relative_to(REPO_ROOT)
        current = copy.read_text(encoding="utf-8") if copy.exists() else None
        if current == canonical_text:
            print(f"  skip {rel}  (already up to date)")
            skipped += 1
            continue
        if DRY_RUN:
            print(f"  would update {rel}")
        else:
            copy.write_text(canonical_text, encoding="utf-8")
            print(f"  wrote {rel}")
        updated += 1

    print(f"\n{'Would update' if DRY_RUN else 'Updated'} {updated} file(s), {skipped} already in sync.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

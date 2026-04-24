#!/usr/bin/env python3
"""
Drift checker for acs_internal.py copies across backend service bundles.

Each Cloud Function bundle is deployed independently, so acs_internal.py is copied into each
bundle directory rather than shared via a package. This script asserts that all copies are
identical in their exported symbols and logic so that drift is caught before deployment.

Usage:
    python backend/scripts/check_acs_internal_sync.py

Exit code 0 = all copies in sync. Exit code 1 = drift detected (prints diff).

Run this in CI before terraform apply or any bundle deploy.
"""

from __future__ import annotations

import ast
import difflib
import hashlib
import pathlib
import sys
import textwrap

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

COPIES: list[pathlib.Path] = [
    REPO_ROOT / "backend" / "auth" / "functions" / "bundle" / "acs_internal.py",
    REPO_ROOT / "backend" / "core" / "functions" / "runner" / "acs_internal.py",
    REPO_ROOT / "backend" / "db" / "functions" / "delete" / "acs_internal.py",
    REPO_ROOT / "backend" / "db" / "functions" / "query" / "acs_internal.py",
    REPO_ROOT / "backend" / "db" / "functions" / "read" / "acs_internal.py",
    REPO_ROOT / "backend" / "db" / "functions" / "upsert" / "acs_internal.py",
    REPO_ROOT / "backend" / "integration" / "functions" / "bundle" / "acs_internal.py",
]

# The canonical source of truth.
CANONICAL = REPO_ROOT / "backend" / "integration" / "functions" / "bundle" / "acs_internal.py"


def _read(p: pathlib.Path) -> str:
    return p.read_text(encoding="utf-8")


def _exported_names(source: str) -> set[str]:
    """Return module-level names (top-level functions, classes, assignments) from source."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
    return names


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main() -> int:
    missing = [p for p in COPIES if not p.exists()]
    if missing:
        print("ERROR: the following expected acs_internal.py copies are missing:")
        for m in missing:
            print(f"  {m.relative_to(REPO_ROOT)}")
        return 1

    canonical_text = _read(CANONICAL)
    canonical_hash = _sha256(canonical_text)
    canonical_names = _exported_names(canonical_text)

    ok = True
    for copy in COPIES:
        if copy == CANONICAL:
            continue
        copy_text = _read(copy)
        copy_hash = _sha256(copy_text)
        copy_names = _exported_names(copy_text)

        rel = copy.relative_to(REPO_ROOT)

        if copy_hash == canonical_hash:
            print(f"  OK  {rel}")
            continue

        ok = False
        print(f"DRIFT {rel}")

        missing_names = canonical_names - copy_names
        extra_names = copy_names - canonical_names
        if missing_names:
            print(f"       missing symbols: {sorted(missing_names)}")
        if extra_names:
            print(f"       extra symbols:   {sorted(extra_names)}")

        diff = list(
            difflib.unified_diff(
                canonical_text.splitlines(keepends=True),
                copy_text.splitlines(keepends=True),
                fromfile=str(CANONICAL.relative_to(REPO_ROOT)),
                tofile=str(rel),
                n=3,
            )
        )
        if diff:
            diff_text = "".join(diff[:60]).encode("ascii", errors="replace").decode("ascii")
            print(textwrap.indent(diff_text, "    "))

    if ok:
        print(f"\nAll {len(COPIES) - 1} copies match canonical {CANONICAL.relative_to(REPO_ROOT)}.")
        return 0

    print(
        "\nFix: run  python backend/scripts/sync_acs_internal.py"
        "  to auto-propagate canonical to all copies."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())

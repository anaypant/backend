"""Shared auth helpers for Atom admin app Firestore buckets (top-level Atom* collections)."""

from __future__ import annotations

import os

_ATOM_ROOT_COLLECTIONS = frozenset(
    {
        "AtomErrorReports",
        "AtomIssues",
        "AtomActivityLog",
        "AtomMeetings",
        "AtomTeams",
        "AtomGoogleCredentials",
    }
)

_ATOM_USER_DIRECTORY_COLLECTIONS = frozenset({"Users", "Realtors", "Internals"})


def _operator_email_allowlist() -> set[str]:
    raw = (os.environ.get("ACS_ATOM_OPERATOR_EMAILS") or "").strip().lower()
    return {x.strip() for x in raw.split(",") if x.strip()}


def is_atom_operator(decoded: dict) -> bool:
    """Firebase admin / role admin, atomAdmin claim, or email in ACS_ATOM_OPERATOR_EMAILS."""
    if not isinstance(decoded, dict):
        return False
    if decoded.get("admin") is True:
        return True
    if decoded.get("role") == "admin":
        return True
    if decoded.get("atomAdmin") is True:
        return True
    em = (decoded.get("email") or "").strip().lower()
    return bool(em and em in _operator_email_allowlist())


def is_atom_managed_document_path(doc_path: str) -> bool:
    parts = [p for p in doc_path.strip().split("/") if p]
    return bool(parts) and parts[0] in _ATOM_ROOT_COLLECTIONS


def is_atom_managed_collection_query_path(col_path: str) -> bool:
    parts = [p for p in col_path.strip().split("/") if p]
    return len(parts) == 1 and parts[0] in _ATOM_ROOT_COLLECTIONS


def is_atom_user_directory_document_path(doc_path: str) -> bool:
    """Top-level ACS profile docs Atom may manage via the public /db API (read/query/upsert/delete)."""
    parts = [p for p in doc_path.strip().split("/") if p]
    return len(parts) == 2 and parts[0] in _ATOM_USER_DIRECTORY_COLLECTIONS


def is_atom_user_directory_collection_query_path(col_path: str) -> bool:
    """Top-level collection listing for user directory (Atom operator + /db/query)."""
    parts = [p for p in col_path.strip().split("/") if p]
    return len(parts) == 1 and parts[0] in _ATOM_USER_DIRECTORY_COLLECTIONS

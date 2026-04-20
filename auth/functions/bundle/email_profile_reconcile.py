"""Resolve Realtor/Internal profile rows per verified email using only the internal DB gateway.

Firebase Admin gives the canonical Auth UID for an address (``get_user_by_email``). All Firestore
writes go through ``/db/read`` and ``/db/upsert`` — user JWT for the signed-in account, and
platform OIDC + ``X-ACS-Acting-Uid`` when acting as the canonical UID (same contract as other
platform DB callers).

Existing users without ``linkedAuthUids`` / index rows get idempotent backfills on the next login.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Callable

from firebase_admin import auth

import firestore_profile as fp

_LOG = logging.getLogger(__name__)

_INDEX_COLLECTION = "ProfileEmailIndex"

# Fields only used for linkage; do not copy onto the canonical profile from a secondary doc.
_SKIP_TRANSFER = frozenset(
    {
        "canonicalProfileUid",
        "linkedAuthUids",
        "ownerUid",
        "createdBy",
    }
)


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def _index_doc_id(role: str, email: str) -> str:
    norm = normalize_email(email)
    return hashlib.sha256(f"{role}:{norm}".encode("utf-8")).hexdigest()


def _unwrap_read(body: Any, status: int) -> dict | None:
    if status == 200 and isinstance(body, dict):
        data = body.get("data")
        if isinstance(data, dict):
            return data
    return None


def _merge_missing_fields(primary: dict, secondary: dict) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, val in secondary.items():
        if key in _SKIP_TRANSFER or val is None:
            continue
        if key not in primary:
            out[key] = val
    return out


def reconcile_after_auth(
    uid: str,
    email: str | None,
    role: str,
    id_token: str,
    *,
    db_read: Callable[..., tuple[dict, int]],
    db_upsert: Callable[..., tuple[dict, int]],
    platform_post: Callable[..., tuple[dict, int]],
) -> None:
    """
    Link profile documents for the same email. Safe to call on every login (idempotent).

    ``platform_post(acting_uid, path, payload)`` must POST JSON to the internal DB gateway with
    platform OIDC + X-ACS-Acting-Uid (see auth bundle ``_post_db_platform``).
    """
    norm = normalize_email(email or "")
    if not norm or "@" not in norm:
        return

    try:
        primary_uid = auth.get_user_by_email(norm).uid
    except Exception as e:
        if type(e).__name__ == "UserNotFoundError":
            _LOG.debug("reconcile: no Firebase user for email (skipping)")
            return
        _LOG.warning("reconcile: get_user_by_email failed: %s", e)
        return

    coll = fp.collection_for_role(role)
    profile_path = f"{coll}/{uid}"
    idx_path = f"{_INDEX_COLLECTION}/{_index_doc_id(role, norm)}"

    if primary_uid == uid:
        _reconcile_single_account(
            uid=uid,
            norm=norm,
            role=role,
            coll=coll,
            profile_path=profile_path,
            idx_path=idx_path,
            id_token=id_token,
            db_read=db_read,
            db_upsert=db_upsert,
            platform_post=platform_post,
        )
        return

    _reconcile_duplicate_auth_uids(
        uid=uid,
        primary_uid=primary_uid,
        norm=norm,
        role=role,
        coll=coll,
        profile_path=profile_path,
        idx_path=idx_path,
        id_token=id_token,
        db_read=db_read,
        db_upsert=db_upsert,
        platform_post=platform_post,
    )


def _reconcile_single_account(
    *,
    uid: str,
    norm: str,
    role: str,
    coll: str,
    profile_path: str,
    idx_path: str,
    id_token: str,
    db_read: Callable[..., tuple[dict, int]],
    db_upsert: Callable[..., tuple[dict, int]],
    platform_post: Callable[..., tuple[dict, int]],
) -> None:
    """Normal case: one Firebase account per email. Backfill index + linkedAuthUids for legacy rows."""
    prof_body, pr_st = db_read(id_token, profile_path)
    prof = _unwrap_read(prof_body, pr_st) or {}

    linked = [x for x in (prof.get("linkedAuthUids") or []) if isinstance(x, str) and x.strip()]
    if uid not in linked:
        linked.append(uid)

    up, ust = db_upsert(
        id_token,
        profile_path,
        {
            "linkedAuthUids": linked,
            "ownerUid": prof.get("ownerUid") or uid,
        },
        merge=True,
    )
    if ust != 200:
        _LOG.warning("reconcile: profile upsert failed uid=%s st=%s body=%s", uid, ust, up)

    idx_body, ist = platform_post(
        uid,
        "/db/upsert/",
        {
            "path": idx_path,
            "data": {
                "ownerUid": uid,
                "normalizedEmail": norm,
                "role": role,
                "primaryUid": uid,
                "linkedUids": linked,
            },
            "merge": True,
        },
    )
    if ist != 200:
        _LOG.warning("reconcile: index upsert failed uid=%s st=%s body=%s", uid, ist, idx_body)


def _reconcile_duplicate_auth_uids(
    *,
    uid: str,
    primary_uid: str,
    norm: str,
    role: str,
    coll: str,
    profile_path: str,
    idx_path: str,
    id_token: str,
    db_read: Callable[..., tuple[dict, int]],
    db_upsert: Callable[..., tuple[dict, int]],
    platform_post: Callable[..., tuple[dict, int]],
) -> None:
    """Rare: multiple Auth UIDs for the same email — merge secondary Firestore doc into canonical."""
    sec_body, sr_st = db_read(id_token, profile_path)
    secondary = _unwrap_read(sec_body, sr_st) or {}

    pri_path = f"{coll}/{primary_uid}"
    pb, p_st = platform_post(
        primary_uid,
        "/db/read/",
        {"path": pri_path},
    )
    primary = _unwrap_read(pb, p_st) or {}

    transfer = _merge_missing_fields(primary, secondary)
    if transfer:
        upb, ust = platform_post(
            primary_uid,
            "/db/upsert/",
            {"path": pri_path, "data": transfer, "merge": True},
        )
        if ust != 200:
            _LOG.warning(
                "reconcile: merge into primary failed primary=%s st=%s body=%s",
                primary_uid,
                ust,
                upb,
            )

    linked_unique: list[str] = []
    seen: set[str] = set()
    for x in (primary_uid, uid):
        if x not in seen:
            seen.add(x)
            linked_unique.append(x)

    upb2, u2st = platform_post(
        primary_uid,
        "/db/upsert/",
        {
            "path": pri_path,
            "data": {"linkedAuthUids": linked_unique, "ownerUid": primary_uid},
            "merge": True,
        },
    )
    if u2st != 200:
        _LOG.warning("reconcile: primary linkedAuthUids failed st=%s body=%s", u2st, upb2)

    stub, sst = db_upsert(
        id_token,
        profile_path,
        {
            "uid": uid,
            "email": norm,
            "canonicalProfileUid": primary_uid,
        },
        merge=True,
    )
    if sst != 200:
        _LOG.warning("reconcile: stub upsert failed st=%s body=%s", sst, stub)

    ix, ist = platform_post(
        primary_uid,
        "/db/upsert/",
        {
            "path": idx_path,
            "data": {
                "ownerUid": primary_uid,
                "normalizedEmail": norm,
                "role": role,
                "primaryUid": primary_uid,
                "linkedUids": linked_unique,
            },
            "merge": True,
        },
    )
    if ist != 200:
        _LOG.warning("reconcile: index upsert (dup) failed st=%s body=%s", ist, ix)

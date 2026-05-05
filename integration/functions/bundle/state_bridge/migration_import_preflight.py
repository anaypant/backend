"""
Expand FUB ``providerLoad`` into ``payload.source_batches`` / ``fubPerson`` **before** POSTing to core.

``migration.import_leads_v1`` would otherwise call core → integration ``from_providers`` (requires
``INTEGRATION_BRIDGE_BASE_URL`` on core-run). CLI/import entrypoint lives in integration and already
has FUB credentials — materializing CRM rows here removes that round-trip for this workflow.
"""

from __future__ import annotations

import copy
import logging
from typing import Any

from state_bridge.acs_merge import merge_acs_patch
from state_bridge.handlers import collect_from_providers_blocks

_logger = logging.getLogger(__name__)

_DEFAULT_FUB_LIST_BATCH = 100
_DEFAULT_MAX_LIST_PAGES = 200
_ABS_MAX_LIST_PAGES = 2000


def _migration_provider(acs: dict[str, Any]) -> str:
    src = acs.get("source") if isinstance(acs.get("source"), dict) else {}
    p = src.get("provider")
    if isinstance(p, str) and p.strip():
        return p.strip().lower()
    return "followupboss"


def _payload_person_id(payload: dict[str, Any]) -> int | str | None:
    raw = payload.get("personId") or payload.get("followupbossPersonId")
    if isinstance(raw, int) and raw > 0:
        return raw
    if isinstance(raw, str) and raw.strip().isdigit():
        return int(raw.strip())
    return None


def _max_followupboss_list_pages(acs: dict[str, Any]) -> int:
    pay = acs.get("payload") if isinstance(acs.get("payload"), dict) else {}
    raw = pay.get("maxListPages", pay.get("maxPages"))
    try:
        n = int(raw) if raw is not None else _DEFAULT_MAX_LIST_PAGES
    except (TypeError, ValueError):
        n = _DEFAULT_MAX_LIST_PAGES
    return max(1, min(n, _ABS_MAX_LIST_PAGES))


def _nonempty_provider_load(acs: dict[str, Any]) -> bool:
    pay = acs.get("payload") if isinstance(acs.get("payload"), dict) else {}
    pl = pay.get("providerLoad")
    return isinstance(pl, list) and any(isinstance(b, dict) for b in pl)


def _parse_source_batches(acs: dict[str, Any]) -> bool:
    """True if payload already has inline CRM rows (core ingress would succeed)."""
    payload = acs.get("payload") if isinstance(acs.get("payload"), dict) else {}
    if isinstance(payload.get("source_batches"), list) and payload["source_batches"]:
        return True
    fp = payload.get("fubPerson")
    if isinstance(fp, dict) and isinstance(fp.get("id"), int):
        return True
    people = payload.get("people")
    if isinstance(people, list) and people:
        return True
    return False


def _ensure_followupboss_provider_load_defaults(acs: dict[str, Any]) -> None:
    """Same rules as core ``import_leads_v1._ensure_followupboss_provider_load_defaults`` (subset)."""
    if _nonempty_provider_load(acs):
        return
    if _parse_source_batches(acs):
        return
    pay = acs.setdefault("payload", {})
    if not isinstance(pay, dict):
        return
    pid = _payload_person_id(pay)
    if pid is not None:
        pay["providerLoad"] = [
            {"provider": "followupboss", "kind": "person_by_id", "payload": {"personId": int(pid)}},
        ]
        return
    if _migration_provider(acs) != "followupboss":
        return
    pay["providerLoad"] = [
        {
            "provider": "followupboss",
            "kind": "people_list_request",
            "payload": {"batchSize": _DEFAULT_FUB_LIST_BATCH, "offset": 0},
        },
    ]


def _fub_people_list_next_token(acs: dict[str, Any]) -> str | None:
    pay = acs.get("payload") if isinstance(acs.get("payload"), dict) else {}
    inte = pay.get("_integration") if isinstance(pay.get("_integration"), dict) else {}
    meta = inte.get("followupbossPeopleMetadata") if isinstance(inte.get("followupbossPeopleMetadata"), dict) else {}
    nt = meta.get("next")
    return nt.strip() if isinstance(nt, str) and nt.strip() else None


def preflight_migration_import_state(uid: str, state: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    """
    Return a **deep copy** of ``state`` with FUB ``providerLoad`` expanded into ``source_batches`` / ``fubPerson``.

    On failure returns ``(state, error_detail)`` with the second element set; caller should not send to core.
    """
    acs = copy.deepcopy(state)
    uid = uid.strip()
    if not uid:
        return acs, "preflight: missing uid"

    _ensure_followupboss_provider_load_defaults(acs)
    pay = acs.get("payload") if isinstance(acs.get("payload"), dict) else {}
    pload = pay.get("providerLoad")
    if not isinstance(pload, list) or not pload:
        return acs, None

    max_pages = _max_followupboss_list_pages(acs)
    pages_fetched = 0
    people_rows = 0

    while True:
        pay_cur = acs.get("payload") if isinstance(acs.get("payload"), dict) else {}
        cur_load = pay_cur.get("providerLoad")
        if not isinstance(cur_load, list):
            break
        blocks = [b for b in cur_load if isinstance(b, dict)]
        if not blocks:
            break

        patch, err = collect_from_providers_blocks(uid, blocks)
        if err:
            return acs, f"preflight from_providers failed: {err}"
        if not isinstance(patch, dict):
            return acs, "preflight from_providers returned empty patch"

        merge_acs_patch(acs, patch)
        pay2 = acs.setdefault("payload", {})
        if not isinstance(pay2, dict):
            pay2 = {}
            acs["payload"] = pay2
        pay2["providerLoad"] = []

        only_people_list = len(blocks) == 1 and blocks[0].get("kind") == "people_list_request"
        if only_people_list:
            pages_fetched += 1
            pf_patch = patch.get("payload") if isinstance(patch.get("payload"), dict) else {}
            sb = pf_patch.get("source_batches")
            if isinstance(sb, list):
                for b in sb:
                    if isinstance(b, dict) and isinstance(b.get("records"), list):
                        people_rows += len(b["records"])
            next_tok = _fub_people_list_next_token(acs)
            if next_tok and pages_fetched < max_pages:
                pl0 = blocks[0].get("payload") if isinstance(blocks[0].get("payload"), dict) else {}
                try:
                    bs = int(pl0.get("batchSize", pl0.get("limit")) or _DEFAULT_FUB_LIST_BATCH)
                except (TypeError, ValueError):
                    bs = _DEFAULT_FUB_LIST_BATCH
                bs = max(1, min(100, bs))
                pay2["providerLoad"] = [
                    {
                        "provider": "followupboss",
                        "kind": "people_list_request",
                        "payload": {"batchSize": bs, "next": next_tok},
                    },
                ]
                continue
            if next_tok and pages_fetched >= max_pages:
                meta = acs.setdefault("metadata", {})
                if isinstance(meta, dict):
                    mig = meta.setdefault("migrationImport", {})
                    if isinstance(mig, dict):
                        mig["listTruncatedByMaxPages"] = True
                        mig["maxListPages"] = max_pages
        break

    meta = acs.setdefault("metadata", {})
    if isinstance(meta, dict):
        ic = meta.setdefault("integrationContext", {})
        if isinstance(ic, dict):
            ic["fromProvidersApplied"] = True
            ic["preflightInIntegration"] = True
        mig2 = meta.setdefault("migrationImport", {})
        if isinstance(mig2, dict) and pages_fetched:
            mig2["followupbossListPagesFetched"] = pages_fetched
            mig2["followupbossPeopleRowsSeen"] = people_rows

    return acs, None


def materialize_provider_load_once(uid: str, state: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    """
    Run **one** ``collect_from_providers`` pass (the current ``payload.providerLoad`` blocks), merge, clear ``providerLoad``.

    Used when the caller already scoped a single FUB list page (e.g. frontend batch route) so core does not
    need ``INTEGRATION_BRIDGE_BASE_URL``.
    """
    acs = copy.deepcopy(state)
    uid = uid.strip()
    if not uid:
        return acs, "preflight: missing uid"

    pay = acs.get("payload") if isinstance(acs.get("payload"), dict) else {}
    pload = pay.get("providerLoad")
    if not isinstance(pload, list) or not pload:
        return acs, None

    blocks = [b for b in pload if isinstance(b, dict)]
    if not blocks:
        pay["providerLoad"] = []
        return acs, None

    patch, err = collect_from_providers_blocks(uid, blocks)
    if err:
        return acs, f"preflight from_providers failed: {err}"
    if not isinstance(patch, dict):
        return acs, "preflight from_providers returned empty patch"

    merge_acs_patch(acs, patch)
    pay2 = acs.setdefault("payload", {})
    if isinstance(pay2, dict):
        pay2["providerLoad"] = []

    meta = acs.setdefault("metadata", {})
    if isinstance(meta, dict):
        ic = meta.setdefault("integrationContext", {})
        if isinstance(ic, dict):
            ic["fromProvidersApplied"] = True
            ic["preflightInIntegration"] = True
            ic["preflightSingleBatch"] = True

    return acs, None

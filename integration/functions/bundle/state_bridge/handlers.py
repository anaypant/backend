"""
ACS ↔ provider state bridges (internal only).

Exposed as ``POST /integrations/internal/state/from_providers`` and
``…/to_providers`` with platform OIDC — called from core-run, not from browsers.

``from_providers``: ``provider_states[]`` → ``acs_patch``.
``to_providers``: ACS snapshot → ``provider_states[]`` (summaries / outbound echoes).
"""

from __future__ import annotations

from typing import Any

from providers.followupboss import fub_people_ops
from store.common import json_response
from store.internal_worker_auth import verify_cloud_tasks_caller


def _merge_payload_fragment(target: dict, fragment: dict[str, Any]) -> None:
    for k, v in fragment.items():
        if k == "source_batches" and isinstance(v, list):
            existing = target.get("source_batches")
            if isinstance(existing, list):
                target["source_batches"] = existing + v
            else:
                target["source_batches"] = v
        elif k == "_integration" and isinstance(v, dict):
            cur = target.get("_integration")
            if isinstance(cur, dict):
                cur.update(v)
            else:
                target["_integration"] = dict(v)
        else:
            target[k] = v


def _from_followupboss_block(uid: str, kind: str, payload: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    if kind == "people_list_request":
        bs, off, nxt = fub_people_ops.parse_list_request(payload if isinstance(payload, dict) else {})
        data, err_st = fub_people_ops.fetch_people_page(uid, batch_size=bs, offset=off, next_token=nxt)
        if err_st is not None:
            return None, f"fub_people_fetch_{err_st}"
        people = data.get("people") if isinstance(data.get("people"), list) else []
        meta = data.get("_metadata") if isinstance(data.get("_metadata"), dict) else {}
        patch: dict[str, Any] = {
            "payload": {
                "source_batches": [{"provider": "followupboss", "records": people}],
                "_integration": {"followupbossPeopleMetadata": meta},
            },
            "source": {"provider": "followupboss", "event_type": "state_bridge.provider_load"},
        }
        return patch, None

    if kind == "raw_records":
        recs = payload.get("records") if isinstance(payload.get("records"), list) else []
        rows = [r for r in recs if isinstance(r, dict)]
        if not rows:
            return None, "raw_records_empty"
        return {
            "payload": {
                "source_batches": [{"provider": "followupboss", "records": rows}],
            },
            "source": {"provider": "followupboss", "event_type": "state_bridge.raw_records"},
        }, None

    return None, f"unsupported_followupboss_kind:{kind}"


def _dispatch_from_block(uid: str, provider: str, kind: str, payload: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    p = provider.strip().lower()
    k = kind.strip()
    if p == "followupboss":
        return _from_followupboss_block(uid, k, payload)
    return None, f"unsupported_provider:{provider}"


def _collect_from_providers(uid: str, blocks: list[Any]) -> tuple[dict[str, Any] | None, str | None]:
    merged: dict[str, Any] = {"payload": {}, "source": None}
    for raw in blocks:
        if not isinstance(raw, dict):
            continue
        prov = raw.get("provider")
        kind = raw.get("kind")
        payload = raw.get("payload") if isinstance(raw.get("payload"), dict) else {}
        if not isinstance(prov, str) or not isinstance(kind, str):
            continue
        patch, err = _dispatch_from_block(uid.strip(), prov, kind, payload)
        if err:
            return None, err
        if not patch:
            continue
        src = patch.get("source")
        if isinstance(src, dict) and merged["source"] is None:
            merged["source"] = dict(src)
        pf = patch.get("payload")
        if isinstance(pf, dict):
            _merge_payload_fragment(merged["payload"], pf)
    if not merged["payload"].get("source_batches"):
        return None, "no_source_batches_produced"
    return merged, None


def _state_from_providers_impl(request, *, uid: str):
    if request.method != "POST":
        return json_response({"error": "method not allowed"}, 405)
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        body = {}
    blocks = body.get("provider_states")
    if not isinstance(blocks, list) or not blocks:
        return json_response({"error": "provider_states_required"}, 400)

    acs_patch, err = _collect_from_providers(uid, blocks)
    if err:
        return json_response({"error": "from_providers_failed", "detail": err}, 400)
    return json_response({"acs_patch": acs_patch}, 200)


def internal_state_from_providers(request):
    """POST /integrations/internal/state/from_providers — platform OIDC (core-run)."""
    if request.method != "POST":
        return json_response({"error": "method not allowed"}, 405)
    _, err = verify_cloud_tasks_caller(request)
    if err:
        return json_response({"error": "unauthorized", "detail": err}, 401)
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        body = {}
    uid = body.get("uid")
    if not isinstance(uid, str) or not uid.strip():
        return json_response({"error": "uid required"}, 400)
    return _state_from_providers_impl(request, uid=uid.strip())


def _to_followupboss_blocks(acs: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    meta = acs.get("metadata") if isinstance(acs.get("metadata"), dict) else {}
    oa = meta.get("outboundActions")
    if isinstance(oa, list) and oa:
        out.append({"provider": "followupboss", "kind": "outbound_actions", "payload": {"actions": oa}})
    mig = meta.get("migrationImport")
    if isinstance(mig, dict):
        out.append(
            {
                "provider": "followupboss",
                "kind": "migration_import_summary",
                "payload": {
                    "normalizedCount": mig.get("normalizedCount"),
                    "persistedCount": mig.get("persistedCount"),
                    "persistFailedCount": mig.get("persistFailedCount"),
                    "persistErrors": mig.get("persistErrors"),
                },
            }
        )
    return out


def _state_to_providers_impl(acs: dict[str, Any]) -> dict[str, Any]:
    blocks: list[dict[str, Any]] = []
    blocks.extend(_to_followupboss_blocks(acs))
    return {"provider_states": blocks}


def internal_state_to_providers(request):
    """POST /integrations/internal/state/to_providers — platform OIDC."""
    if request.method != "POST":
        return json_response({"error": "method not allowed"}, 405)
    _, err = verify_cloud_tasks_caller(request)
    if err:
        return json_response({"error": "unauthorized", "detail": err}, 401)
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        body = {}
    uid = body.get("uid")
    if not isinstance(uid, str) or not uid.strip():
        return json_response({"error": "uid required"}, 400)
    uid = uid.strip()
    acs = body.get("acs_state")
    if not isinstance(acs, dict):
        return json_response({"error": "acs_state object required"}, 400)
    if isinstance(acs.get("user_id"), str) and acs.get("user_id").strip() and acs.get("user_id") != uid:
        return json_response({"error": "acs_state user_id mismatch"}, 403)
    out = _state_to_providers_impl(acs)
    return json_response(out, 200)

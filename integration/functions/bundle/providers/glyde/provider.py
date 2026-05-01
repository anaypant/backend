"""Glyde integration provider — routes for settings, ads, hot-leads, drip quarantine, and scheduler."""

from __future__ import annotations

import datetime
import json
import logging
import os

from dispatcher.core_client import send_state_to_core
from providers.ads import resolve_ads_provider
from providers.ads.base import AdsProviderError, dispatch_ad_action
from store.authn import resolve_realtor_bearer
from store.common import (
    db_origin,
    json_response,
    post_json_platform,
    integration_auth_error_response,
)
from store.internal_worker_auth import verify_cloud_tasks_caller

_logger = logging.getLogger(__name__)


def _db_read(path: str, *, acting_uid: str) -> tuple[dict, int]:
    url = db_origin().rstrip("/") + "/db/read/"
    return post_json_platform(url, {"path": path}, acting_uid=acting_uid)


def _db_upsert(path: str, data: dict, *, acting_uid: str) -> tuple[dict, int]:
    url = db_origin().rstrip("/") + "/db/upsert/"
    return post_json_platform(url, {"path": path, "data": data, "merge": True}, acting_uid=acting_uid)


def _db_query(path: str, filters: list, *, acting_uid: str, limit: int = 50) -> tuple[dict, int]:
    url = db_origin().rstrip("/") + "/db/query/"
    return post_json_platform(url, {"path": path, "filters": filters, "limit": limit}, acting_uid=acting_uid)


def _iso_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class GlydeProvider:
    """Handles /integrations/glyde/* routes."""

    # ---------- GlydeSettings ----------

    def get_settings(self, request):
        decoded, err, _token = resolve_realtor_bearer(request)
        if err:
            return integration_auth_error_response(err)
        uid = decoded["uid"]

        body, st = _db_read(f"Realtors/{uid}/GlydeSettings/config", acting_uid=uid)
        if st == 404:
            return json_response({"data": {}}, 200)
        if st >= 400:
            return json_response({"error": f"db read failed: {st}"}, 502)
        return json_response({"data": body.get("data") or {}}, 200)

    def update_settings(self, request):
        decoded, err, _token = resolve_realtor_bearer(request)
        if err:
            return integration_auth_error_response(err)
        uid = decoded["uid"]

        try:
            payload = request.get_json(force=True, silent=True) or {}
        except Exception:
            payload = {}

        if not isinstance(payload, dict):
            return json_response({"error": "JSON object body required"}, 400)

        _ALLOWED = {
            "enabledWorkflows", "autoReplyEnabled", "autoReplyTone",
            "dripCooldownDays", "hotLeadThreshold", "hotLeadMaxCount",
            "googleAdsAccountId", "metaAdsAccountId",
            "leadLaneAutoMode",
        }
        data = {k: v for k, v in payload.items() if k in _ALLOWED}
        data["ownerUid"] = uid
        data["updatedAt"] = _iso_now()

        _, st = _db_upsert(f"Realtors/{uid}/GlydeSettings/config", data, acting_uid=uid)
        if st >= 400:
            return json_response({"error": f"db write failed: {st}"}, 502)
        return json_response({"ok": True, "updatedAt": data["updatedAt"]}, 200)

    # ---------- Ads management ----------

    def manage_ads(self, request):
        decoded, err, _token = resolve_realtor_bearer(request)
        if err:
            return integration_auth_error_response(err)
        uid = decoded["uid"]

        try:
            payload = request.get_json(force=True, silent=True) or {}
        except Exception:
            payload = {}

        if not isinstance(payload, dict):
            return json_response({"error": "JSON object body required"}, 400)

        action = str(payload.get("action") or "").lower().strip()
        if action not in ("create", "update", "pause", "delete", "status"):
            return json_response({"error": "action must be create|update|pause|delete|status"}, 400)

        settings_body, _ = _db_read(f"Realtors/{uid}/GlydeSettings/config", acting_uid=uid)
        settings = settings_body.get("data") if isinstance(settings_body.get("data"), dict) else {}

        platforms = payload.get("platforms") or ["google_ads", "meta_ads"]
        if isinstance(platforms, str):
            platforms = [platforms]

        results: list[dict] = []
        errors: list[dict] = []

        for platform in platforms:
            provider = resolve_ads_provider(platform)
            if not provider:
                errors.append({"platform": platform, "error": f"unsupported platform '{platform}'"})
                continue

            acct_id = None
            if platform == "google_ads":
                acct_id = payload.get("googleAdsAccountId") or settings.get("googleAdsAccountId")
            elif platform == "meta_ads":
                acct_id = payload.get("metaAdsAccountId") or settings.get("metaAdsAccountId")

            if not acct_id and action != "status":
                errors.append({"platform": platform, "error": f"account_id not configured for {platform}"})
                continue

            try:
                if action == "status":
                    result = provider.get_campaign_status(
                        account_id=acct_id or "",
                        campaign_id=str(payload.get("campaignId") or ""),
                    )
                else:
                    result = dispatch_ad_action(
                        provider,
                        action=action,
                        account_id=acct_id,
                        campaign_id=payload.get("campaignId"),
                        urls=payload.get("urls"),
                        ad_copy=payload.get("adCopy"),
                        daily_budget_usd=payload.get("dailyBudgetUsd"),
                        objective=payload.get("objective"),
                        target_audience=payload.get("targetAudience"),
                    )
                results.append(result)

                if action in ("create", "update") and result.get("campaignId"):
                    _, _ = _db_upsert(
                        f"Realtors/{uid}/AdCampaigns/{result['campaignId']}",
                        {
                            "ownerUid": uid,
                            "campaignId": result["campaignId"],
                            "platform": platform,
                            "action": action,
                            "status": result.get("status") or "active",
                            "urls": payload.get("urls") or [],
                            "updatedAt": _iso_now(),
                        },
                        acting_uid=uid,
                    )
            except AdsProviderError as e:
                errors.append({"platform": platform, "error": str(e), "status_code": e.status_code})
            except Exception as e:
                _logger.exception("ads manage_ads unexpected error for %s", platform)
                errors.append({"platform": platform, "error": str(e)})

        ok = len(results) > 0
        return json_response({"ok": ok, "results": results, "errors": errors}, 200 if ok else 502)

    # ---------- Hot leads manual refresh ----------

    def refresh_hot_leads(self, request):
        decoded, err, _token = resolve_realtor_bearer(request)
        if err:
            return integration_auth_error_response(err)
        uid = decoded["uid"]

        state: dict = {
            "state_version": 1,
            "correlation_id": f"hot_leads_manual_{uid}",
            "source": {"provider": "glyde", "event_type": "manual_hot_leads_refresh"},
            "user_id": uid,
            "payload": {},
            "metadata": {
                "execution_policy": {
                    "volatile_external_allowed": False,
                    "integration_maintenance_allowed": True,
                }
            },
        }
        core_body, core_status = send_state_to_core(state, workflow_id="lead.hot_notify_v1")
        ok = core_status < 400
        return json_response({"ok": ok, "core_http_status": core_status, "status": core_body.get("status")}, 200 if ok else 502)

    # ---------- Drip quarantine ----------

    def manage_quarantine(self, request):
        decoded, err, _token = resolve_realtor_bearer(request)
        if err:
            return integration_auth_error_response(err)
        uid = decoded["uid"]

        try:
            payload = request.get_json(force=True, silent=True) or {}
        except Exception:
            payload = {}

        canonical_id = str(payload.get("canonicalLeadId") or "").strip()
        if not canonical_id:
            return json_response({"error": "canonicalLeadId required"}, 400)

        quarantine = bool(payload.get("quarantine", True))
        _, st = _db_upsert(
            f"Realtors/{uid}/Leads/{canonical_id}",
            {"glydeQuarantined": quarantine, "glydeQuarantineUpdatedAt": _iso_now()},
            acting_uid=uid,
        )
        if st >= 400:
            return json_response({"error": f"db write failed: {st}"}, 502)
        return json_response({"ok": True, "canonicalLeadId": canonical_id, "quarantine": quarantine}, 200)

    # ---------- Lead lane (active vs nurture) ----------

    def set_lead_lane(self, request):
        decoded, err, _token = resolve_realtor_bearer(request)
        if err:
            return integration_auth_error_response(err)
        uid = decoded["uid"]

        try:
            payload = request.get_json(force=True, silent=True) or {}
        except Exception:
            payload = {}

        if not isinstance(payload, dict):
            return json_response({"error": "JSON object body required"}, 400)

        canonical_id = str(payload.get("canonicalLeadId") or "").strip()
        if not canonical_id:
            return json_response({"error": "canonicalLeadId required"}, 400)

        lane = str(payload.get("glydeLeadLane") or payload.get("lane") or "").strip().lower()
        if lane not in ("active", "nurture"):
            return json_response({"error": "glydeLeadLane must be active|nurture"}, 400)

        pinned_raw = payload.get("glydeLaneUserPinned")
        if pinned_raw is None:
            user_pinned = True
        else:
            user_pinned = bool(pinned_raw)

        merge = {
            "glydeLeadLane": lane,
            "glydeLaneUserPinned": user_pinned,
            "glydeLaneUpdatedAt": _iso_now(),
            "glydeLaneReason": "Set via Glyde integration API.",
            "glydeLaneReasonCodes": ["user_api"],
            "glydeLaneSource": "user_api",
        }
        _, st = _db_upsert(f"Realtors/{uid}/Leads/{canonical_id}", merge, acting_uid=uid)
        if st >= 400:
            return json_response({"error": f"db write failed: {st}"}, 502)
        return json_response(
            {
                "ok": True,
                "canonicalLeadId": canonical_id,
                "glydeLeadLane": lane,
                "glydeLaneUserPinned": user_pinned,
                "updatedAt": merge["glydeLaneUpdatedAt"],
            },
            200,
        )

    # ---------- Cloud Scheduler inbound ----------

    def scheduler_trigger(self, request):
        """Internal-only endpoint; requires platform service-account OIDC token."""
        _, err = verify_cloud_tasks_caller(request)
        if err:
            return json_response({"error": err}, 401)

        try:
            payload = request.get_json(force=True, silent=True) or {}
        except Exception:
            payload = {}

        job = str(payload.get("job") or "").strip()
        uid = str(payload.get("uid") or "").strip()

        if not uid:
            return json_response({"error": "uid required in scheduler payload"}, 400)

        workflow_map = {
            "glyde-drip-daily": "campaign.drip_v1",
            "glyde-hot-leads-daily": "lead.hot_notify_v1",
        }
        workflow_id = workflow_map.get(job)
        if not workflow_id:
            return json_response({"error": f"unknown job '{job}'"}, 400)

        state: dict = {
            "state_version": 1,
            "correlation_id": f"scheduler_{job}_{uid}",
            "source": {"provider": "glyde_scheduler", "event_type": job},
            "user_id": uid,
            "payload": {"scheduledJob": job},
            "metadata": {
                "execution_policy": {
                    "volatile_external_allowed": True,
                    "integration_maintenance_allowed": True,
                }
            },
        }
        core_body, core_status = send_state_to_core(state, workflow_id=workflow_id)
        ok = core_status < 400
        return json_response({"ok": ok, "job": job, "workflow_id": workflow_id, "core_http_status": core_status}, 200 if ok else 502)

    # ---------- Ad campaigns list ----------

    def list_campaigns(self, request):
        decoded, err, _token = resolve_realtor_bearer(request)
        if err:
            return integration_auth_error_response(err)
        uid = decoded["uid"]

        body, st = _db_query(
            f"Realtors/{uid}/AdCampaigns",
            [{"field": "ownerUid", "op": "==", "value": uid}],
            acting_uid=uid,
            limit=50,
        )
        if st >= 400:
            return json_response({"error": f"db query failed: {st}"}, 502)

        items = []
        if isinstance(body.get("items"), list):
            for item in body["items"]:
                data = item.get("data") if isinstance(item.get("data"), dict) else {}
                if data:
                    items.append(data)

        return json_response({"ok": True, "campaigns": items, "count": len(items)}, 200)

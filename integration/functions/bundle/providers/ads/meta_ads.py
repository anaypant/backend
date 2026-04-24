"""Meta (Facebook/Instagram) Ads Marketing API provider.

Uses the facebook-business SDK.
Credentials are resolved from Secret Manager via the realtor's metaAdsAccountId
and an access token stored per realtor.

Environment variables:
  META_ADS_APP_ID              — required; Meta App ID
  META_ADS_APP_SECRET          — required; Meta App Secret
  META_ADS_SECRET_REF          — optional Secret Manager ref for access token JSON
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any

from providers.ads.base import AdsProvider, AdsProviderError

_logger = logging.getLogger(__name__)

_PLATFORM = "meta_ads"


class MetaAdsProvider(AdsProvider):
    """Meta Marketing API provider."""

    @property
    def platform_key(self) -> str:
        return _PLATFORM

    def _api(self, account_id: str):
        """Return (FacebookAdsApi instance, AdAccount resource)."""
        try:
            from facebook_business.api import FacebookAdsApi  # type: ignore[import]
            from facebook_business.adobjects.adaccount import AdAccount  # type: ignore[import]
        except ImportError as exc:
            raise AdsProviderError(
                "facebook-business library not installed; add 'facebook-business' to requirements.txt",
                platform=_PLATFORM,
            ) from exc

        app_id = (os.environ.get("META_ADS_APP_ID") or "").strip()
        app_secret = (os.environ.get("META_ADS_APP_SECRET") or "").strip()
        if not app_id or not app_secret:
            raise AdsProviderError("META_ADS_APP_ID / META_ADS_APP_SECRET not set", platform=_PLATFORM, status_code=503)

        access_token: str | None = None
        secret_ref = (os.environ.get("META_ADS_SECRET_REF") or "").strip()
        if secret_ref:
            try:
                from store.secret_repo import get_secret  # type: ignore[import]
                raw = get_secret(secret_ref)
                if isinstance(raw, str):
                    creds = json.loads(raw)
                    access_token = creds.get("access_token")
            except Exception as e:
                _logger.warning("meta_ads: failed to load token from secret: %s", e)

        if not access_token:
            raise AdsProviderError("Meta Ads access token not configured", platform=_PLATFORM, status_code=503)

        api = FacebookAdsApi.init(app_id, app_secret, access_token)
        acct_id = account_id if account_id.startswith("act_") else f"act_{account_id}"
        return api, AdAccount(acct_id)

    def create_campaign(
        self,
        *,
        account_id: str,
        urls: list[str],
        headline: str,
        description: str,
        call_to_action: str,
        daily_budget_usd: float,
        keywords: list[str] | None = None,
        objective: str = "traffic",
        target_audience: str | None = None,
    ) -> dict[str, Any]:
        from facebook_business.adobjects.campaign import Campaign  # type: ignore[import]

        _api, ad_account = self._api(account_id)

        objective_map = {
            "traffic": "LINK_CLICKS",
            "leads": "LEAD_GENERATION",
            "brand_awareness": "BRAND_AWARENESS",
            "conversions": "CONVERSIONS",
        }
        fb_objective = objective_map.get((objective or "traffic").lower(), "LINK_CLICKS")

        campaign = ad_account.create_campaign(
            fields=[Campaign.Field.name, Campaign.Field.status],
            params={
                Campaign.Field.name: f"glyde_{uuid.uuid4().hex[:8]}",
                Campaign.Field.objective: fb_objective,
                Campaign.Field.status: Campaign.Status.active,
                Campaign.Field.daily_budget: int(daily_budget_usd * 100),
                "special_ad_categories": [],
            },
        )
        campaign_id = campaign["id"]
        _logger.info("meta_ads: created campaign %s for account %s", campaign_id, account_id)
        return {"platform": _PLATFORM, "campaignId": campaign_id, "status": "active"}

    def update_campaign(
        self,
        *,
        account_id: str,
        campaign_id: str,
        urls: list[str] | None = None,
        headline: str | None = None,
        description: str | None = None,
        daily_budget_usd: float | None = None,
    ) -> dict[str, Any]:
        from facebook_business.adobjects.campaign import Campaign  # type: ignore[import]

        _api, _ = self._api(account_id)
        campaign = Campaign(campaign_id)
        params: dict[str, Any] = {}
        if daily_budget_usd is not None:
            params["daily_budget"] = int(daily_budget_usd * 100)
        if params:
            campaign.api_update(params=params)
        _logger.info("meta_ads: updated campaign %s", campaign_id)
        return {"platform": _PLATFORM, "campaignId": campaign_id, "status": "updated"}

    def pause_campaign(self, *, account_id: str, campaign_id: str) -> dict[str, Any]:
        from facebook_business.adobjects.campaign import Campaign  # type: ignore[import]

        _api, _ = self._api(account_id)
        campaign = Campaign(campaign_id)
        campaign.api_update(params={"status": Campaign.Status.paused})
        _logger.info("meta_ads: paused campaign %s", campaign_id)
        return {"platform": _PLATFORM, "campaignId": campaign_id, "status": "paused"}

    def delete_campaign(self, *, account_id: str, campaign_id: str) -> dict[str, Any]:
        from facebook_business.adobjects.campaign import Campaign  # type: ignore[import]

        _api, _ = self._api(account_id)
        campaign = Campaign(campaign_id)
        campaign.api_delete()
        _logger.info("meta_ads: deleted campaign %s", campaign_id)
        return {"platform": _PLATFORM, "campaignId": campaign_id, "status": "deleted"}

    def get_campaign_status(self, *, account_id: str, campaign_id: str) -> dict[str, Any]:
        from facebook_business.adobjects.campaign import Campaign  # type: ignore[import]

        _api, _ = self._api(account_id)
        campaign = Campaign(campaign_id)
        data = campaign.api_get(fields=["id", "name", "status", "effective_status"])
        return {
            "platform": _PLATFORM,
            "campaignId": str(data.get("id") or campaign_id),
            "name": data.get("name"),
            "status": str(data.get("effective_status") or data.get("status") or "unknown").lower(),
        }

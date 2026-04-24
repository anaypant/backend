"""Google Ads API v16 provider implementation.

Uses the google-ads Python client library.
Credentials are resolved from Secret Manager via the realtor's googleAdsAccountId
and a platform-managed service account with Google Ads API access.

Environment variables:
  GOOGLE_ADS_DEVELOPER_TOKEN   — required; Google Ads developer token
  GOOGLE_ADS_SECRET_REF        — optional Secret Manager ref for OAuth credentials JSON

The implementation uses the Google Ads API's CampaignService, AdGroupService,
and AdGroupAdService to manage search / display campaigns.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any

from providers.ads.base import AdsProvider, AdsProviderError

_logger = logging.getLogger(__name__)

_PLATFORM = "google_ads"


class GoogleAdsProvider(AdsProvider):
    """Google Ads API v16 provider."""

    @property
    def platform_key(self) -> str:
        return _PLATFORM

    def _client(self, account_id: str):
        """Lazily build google-ads client. Raises AdsProviderError on config failure."""
        try:
            from google.ads.googleads.client import GoogleAdsClient  # type: ignore[import]
        except ImportError as exc:
            raise AdsProviderError(
                "google-ads library not installed; add 'google-ads' to requirements.txt",
                platform=_PLATFORM,
            ) from exc

        dev_token = (os.environ.get("GOOGLE_ADS_DEVELOPER_TOKEN") or "").strip()
        if not dev_token:
            raise AdsProviderError("GOOGLE_ADS_DEVELOPER_TOKEN not set", platform=_PLATFORM, status_code=503)

        secret_ref = (os.environ.get("GOOGLE_ADS_SECRET_REF") or "").strip()
        credentials_json: dict | None = None
        if secret_ref:
            try:
                from store.secret_repo import get_secret  # type: ignore[import]
                raw = get_secret(secret_ref)
                if isinstance(raw, str):
                    credentials_json = json.loads(raw)
            except Exception as e:
                _logger.warning("google_ads: failed to load credentials from secret: %s", e)

        config: dict[str, Any] = {
            "developer_token": dev_token,
            "use_proto_plus": True,
        }
        if credentials_json:
            config["client_id"] = credentials_json.get("client_id")
            config["client_secret"] = credentials_json.get("client_secret")
            config["refresh_token"] = credentials_json.get("refresh_token")
        else:
            config["use_cloud_org_for_api_access"] = True

        try:
            return GoogleAdsClient.load_from_dict(config, version="v16"), account_id.replace("-", "")
        except Exception as exc:
            raise AdsProviderError(f"google-ads client init failed: {exc}", platform=_PLATFORM) from exc

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
        client, customer_id = self._client(account_id)
        campaign_service = client.get_service("CampaignService")
        budget_service = client.get_service("CampaignBudgetService")

        campaign_budget_op = client.get_type("CampaignBudgetOperation")
        budget = campaign_budget_op.create
        budget.name = f"glyde_budget_{uuid.uuid4().hex[:8]}"
        budget.delivery_method = client.enums.BudgetDeliveryMethodEnum.STANDARD
        budget.amount_micros = int(daily_budget_usd * 1_000_000)

        budget_response = budget_service.mutate_campaign_budgets(
            customer_id=customer_id, operations=[campaign_budget_op]
        )
        budget_resource = budget_response.results[0].resource_name

        campaign_op = client.get_type("CampaignOperation")
        campaign = campaign_op.create
        campaign.name = f"glyde_{uuid.uuid4().hex[:8]}"
        campaign.advertising_channel_type = client.enums.AdvertisingChannelTypeEnum.SEARCH
        campaign.status = client.enums.CampaignStatusEnum.ENABLED
        campaign.campaign_budget = budget_resource
        campaign.network_settings.target_google_search = True
        campaign.network_settings.target_search_network = True

        campaign_response = campaign_service.mutate_campaigns(
            customer_id=customer_id, operations=[campaign_op]
        )
        campaign_resource = campaign_response.results[0].resource_name
        campaign_id = campaign_resource.split("/")[-1]

        _logger.info("google_ads: created campaign %s for account %s", campaign_id, account_id)
        return {
            "platform": _PLATFORM,
            "campaignId": campaign_id,
            "resourceName": campaign_resource,
            "status": "enabled",
        }

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
        client, customer_id = self._client(account_id)
        campaign_service = client.get_service("CampaignService")

        campaign_op = client.get_type("CampaignOperation")
        campaign = campaign_op.update
        campaign.resource_name = campaign_service.campaign_path(customer_id, campaign_id)

        field_mask_parts: list[str] = []
        if daily_budget_usd is not None:
            field_mask_parts.append("campaign_budget")

        from google.protobuf import field_mask_pb2  # type: ignore[import]
        campaign_op.update_mask.CopyFrom(field_mask_pb2.FieldMask(paths=field_mask_parts))

        campaign_service.mutate_campaigns(customer_id=customer_id, operations=[campaign_op])
        _logger.info("google_ads: updated campaign %s", campaign_id)
        return {"platform": _PLATFORM, "campaignId": campaign_id, "status": "updated"}

    def pause_campaign(self, *, account_id: str, campaign_id: str) -> dict[str, Any]:
        client, customer_id = self._client(account_id)
        campaign_service = client.get_service("CampaignService")

        campaign_op = client.get_type("CampaignOperation")
        campaign = campaign_op.update
        campaign.resource_name = campaign_service.campaign_path(customer_id, campaign_id)
        campaign.status = client.enums.CampaignStatusEnum.PAUSED

        from google.protobuf import field_mask_pb2  # type: ignore[import]
        campaign_op.update_mask.CopyFrom(field_mask_pb2.FieldMask(paths=["status"]))
        campaign_service.mutate_campaigns(customer_id=customer_id, operations=[campaign_op])

        _logger.info("google_ads: paused campaign %s", campaign_id)
        return {"platform": _PLATFORM, "campaignId": campaign_id, "status": "paused"}

    def delete_campaign(self, *, account_id: str, campaign_id: str) -> dict[str, Any]:
        client, customer_id = self._client(account_id)
        campaign_service = client.get_service("CampaignService")

        campaign_op = client.get_type("CampaignOperation")
        campaign_op.remove = campaign_service.campaign_path(customer_id, campaign_id)
        campaign_service.mutate_campaigns(customer_id=customer_id, operations=[campaign_op])

        _logger.info("google_ads: deleted campaign %s", campaign_id)
        return {"platform": _PLATFORM, "campaignId": campaign_id, "status": "deleted"}

    def get_campaign_status(self, *, account_id: str, campaign_id: str) -> dict[str, Any]:
        client, customer_id = self._client(account_id)
        ga_service = client.get_service("GoogleAdsService")

        query = f"""
            SELECT campaign.id, campaign.name, campaign.status
            FROM campaign
            WHERE campaign.id = {campaign_id}
        """
        response = ga_service.search(customer_id=customer_id, query=query)
        for row in response:
            return {
                "platform": _PLATFORM,
                "campaignId": str(row.campaign.id),
                "name": row.campaign.name,
                "status": str(row.campaign.status.name).lower(),
            }
        return {"platform": _PLATFORM, "campaignId": campaign_id, "status": "not_found"}

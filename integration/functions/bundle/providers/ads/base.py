"""Abstract base interface for ad platform providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class AdsProviderError(Exception):
    """Raised when an ad platform API call fails."""

    def __init__(self, message: str, *, platform: str, status_code: int = 500):
        super().__init__(message)
        self.platform = platform
        self.status_code = status_code


class AdsProvider(ABC):
    """Common interface for Google Ads and Meta Ads providers."""

    @property
    @abstractmethod
    def platform_key(self) -> str:
        """Canonical platform identifier (e.g. 'google_ads', 'meta_ads')."""

    @abstractmethod
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
        """Create a new ad campaign. Returns dict with at least ``campaignId``."""

    @abstractmethod
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
        """Update an existing campaign. Returns dict with ``campaignId``."""

    @abstractmethod
    def pause_campaign(self, *, account_id: str, campaign_id: str) -> dict[str, Any]:
        """Pause a running campaign."""

    @abstractmethod
    def delete_campaign(self, *, account_id: str, campaign_id: str) -> dict[str, Any]:
        """Delete / remove a campaign."""

    @abstractmethod
    def get_campaign_status(self, *, account_id: str, campaign_id: str) -> dict[str, Any]:
        """Fetch current status of a campaign."""


def dispatch_ad_action(
    provider: AdsProvider,
    *,
    action: str,
    account_id: str,
    campaign_id: str | None = None,
    urls: list[str] | None = None,
    ad_copy: dict[str, Any] | None = None,
    daily_budget_usd: float | None = None,
    objective: str | None = None,
    target_audience: str | None = None,
) -> dict[str, Any]:
    """Route an action string to the appropriate provider method."""
    copy = ad_copy or {}
    action = (action or "").lower().strip()

    if action == "create":
        return provider.create_campaign(
            account_id=account_id,
            urls=urls or [],
            headline=str(copy.get("headline") or ""),
            description=str(copy.get("description") or ""),
            call_to_action=str(copy.get("call_to_action") or "Learn More"),
            daily_budget_usd=float(daily_budget_usd or 10.0),
            keywords=copy.get("keywords"),
            objective=objective or "traffic",
            target_audience=target_audience,
        )
    if action == "update":
        if not campaign_id:
            raise AdsProviderError("campaign_id required for update", platform=provider.platform_key)
        return provider.update_campaign(
            account_id=account_id,
            campaign_id=campaign_id,
            urls=urls,
            headline=copy.get("headline"),
            description=copy.get("description"),
            daily_budget_usd=daily_budget_usd,
        )
    if action == "pause":
        if not campaign_id:
            raise AdsProviderError("campaign_id required for pause", platform=provider.platform_key)
        return provider.pause_campaign(account_id=account_id, campaign_id=campaign_id)
    if action == "delete":
        if not campaign_id:
            raise AdsProviderError("campaign_id required for delete", platform=provider.platform_key)
        return provider.delete_campaign(account_id=account_id, campaign_id=campaign_id)

    raise AdsProviderError(f"unknown action '{action}'", platform=provider.platform_key, status_code=400)

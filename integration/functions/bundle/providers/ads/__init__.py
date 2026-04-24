"""Ads provider registry — resolve platform key to AdsProvider instance."""

from __future__ import annotations

from providers.ads.base import AdsProvider
from providers.ads.google_ads import GoogleAdsProvider
from providers.ads.meta_ads import MetaAdsProvider

_PROVIDERS: dict[str, AdsProvider] = {
    "google_ads": GoogleAdsProvider(),
    "meta_ads": MetaAdsProvider(),
}


def resolve_ads_provider(platform_key: str) -> AdsProvider | None:
    """Return the AdsProvider for a platform key, or None if not registered."""
    return _PROVIDERS.get((platform_key or "").lower().strip())


def list_platform_keys() -> list[str]:
    return sorted(_PROVIDERS.keys())

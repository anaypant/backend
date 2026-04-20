"""Configurable browser-simulation and fetch limits (anti-automation friction, polite crawling)."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class BrowserSimSettings:
    """
    Headers and pacing to reduce trivial bot fingerprinting (not a CAPTCHA solver).

    Tuning via environment keeps deploy-time policy explicit.
    """

    user_agent: str
    accept_language: str
    accept: str
    sec_ch_ua: str
    sec_ch_ua_mobile: str
    sec_ch_ua_platform: str
    referer: str
    delay_before_request_min_s: float
    delay_before_request_max_s: float
    max_response_bytes: int
    fetch_timeout_s: int
    max_redirects: int
    per_host_min_interval_s: float

    @classmethod
    def from_env(cls) -> BrowserSimSettings:
        ua = (
            os.environ.get("ACS_BROWSER_USER_AGENT")
            or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ).strip()
        return cls(
            user_agent=ua[:512],
            accept_language=(os.environ.get("ACS_BROWSER_ACCEPT_LANGUAGE") or "en-US,en;q=0.9")[:128],
            accept=(os.environ.get("ACS_BROWSER_ACCEPT") or "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8")[:256],
            sec_ch_ua=(os.environ.get("ACS_BROWSER_SEC_CH_UA") or '"Chromium";v="122", "Not(A:Brand";v="24"')[:256],
            sec_ch_ua_mobile=(os.environ.get("ACS_BROWSER_SEC_CH_UA_MOBILE") or "?0")[:8],
            sec_ch_ua_platform=(os.environ.get("ACS_BROWSER_SEC_CH_UA_PLATFORM") or '"Windows"')[:64],
            referer=(os.environ.get("ACS_BROWSER_REFERER") or "https://www.google.com/")[:512],
            delay_before_request_min_s=max(0.0, _env_float("ACS_BROWSER_DELAY_MIN_S", 0.35)),
            delay_before_request_max_s=max(0.0, _env_float("ACS_BROWSER_DELAY_MAX_S", 1.1)),
            max_response_bytes=max(50_000, _env_int("ACS_BROWSER_MAX_RESPONSE_BYTES", 1_500_000)),
            fetch_timeout_s=max(5, _env_int("ACS_BROWSER_FETCH_TIMEOUT_S", 25)),
            max_redirects=max(1, min(10, _env_int("ACS_BROWSER_MAX_REDIRECTS", 5))),
            per_host_min_interval_s=max(0.0, _env_float("ACS_BROWSER_PER_HOST_MIN_INTERVAL_S", 0.5)),
        )

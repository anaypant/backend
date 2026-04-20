"""Browser-like HTTP GET using stdlib (TLS, headers, pacing)."""

from __future__ import annotations

import random
import time
import urllib.error
import urllib.parse
import urllib.request
from threading import Lock

from clients.web_research.settings import BrowserSimSettings
from clients.web_research.url_blacklist import is_blocked_url


class BrowserFetchSession:
    """
    Shared session for concurrent workers: per-host pacing + randomized delay.

    urllib follows redirects by default (RFC-compliant). This is not a headless browser;
    it approximates common browser request metadata. For JS-heavy pages, integrate a
    managed rendering service separately.
    """

    def __init__(self, settings: BrowserSimSettings | None = None) -> None:
        self.settings = settings or BrowserSimSettings.from_env()
        self._lock = Lock()
        self._last_fetch_mono_by_host: dict[str, float] = {}

    def _headers(self) -> dict[str, str]:
        s = self.settings
        return {
            "User-Agent": s.user_agent,
            "Accept": s.accept,
            "Accept-Language": s.accept_language,
            "Accept-Encoding": "gzip, deflate, br",
            "Sec-Ch-Ua": s.sec_ch_ua,
            "Sec-Ch-Ua-Mobile": s.sec_ch_ua_mobile,
            "Sec-Ch-Ua-Platform": s.sec_ch_ua_platform,
            "Referer": s.referer,
            "Upgrade-Insecure-Requests": "1",
            "DNT": "1",
            "Connection": "close",
        }

    def _pace(self, host: str) -> None:
        lo, hi = self.settings.delay_before_request_min_s, self.settings.delay_before_request_max_s
        if hi > 0 and hi >= lo:
            time.sleep(random.uniform(lo, hi))
        with self._lock:
            now = time.monotonic()
            last = self._last_fetch_mono_by_host.get(host, 0.0)
            wait = self.settings.per_host_min_interval_s - (now - last)
            if wait > 0:
                time.sleep(wait)
            self._last_fetch_mono_by_host[host] = time.monotonic()

    def fetch_url(self, url: str) -> tuple[bytes, int, str | None, str]:
        """Return ``(body_bytes, http_status, final_url, content_type)``."""
        if is_blocked_url(url):
            return b"", 451, None, ""

        current = url.strip()
        if not current:
            return b"", 400, None, ""

        parsed = urllib.parse.urlparse(current)
        host = (parsed.hostname or "").lower()
        if not host:
            return b"", 400, None, ""

        self._pace(host)

        req = urllib.request.Request(current, method="GET", headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=self.settings.fetch_timeout_s) as resp:
                raw = resp.read(self.settings.max_response_bytes + 1)
                if len(raw) > self.settings.max_response_bytes:
                    raw = raw[: self.settings.max_response_bytes]
                final_url = current
                if hasattr(resp, "geturl"):
                    fu = resp.geturl()
                    if isinstance(fu, str) and fu.strip():
                        final_url = fu.strip()
                if is_blocked_url(final_url):
                    return b"", 451, final_url, ""
                ctype = resp.headers.get("Content-Type") or ""
                return raw, int(resp.status), final_url, str(ctype)
        except urllib.error.HTTPError as e:
            try:
                raw = e.read(self.settings.max_response_bytes + 1)
            except Exception:
                raw = b""
            if len(raw) > self.settings.max_response_bytes:
                raw = raw[: self.settings.max_response_bytes]
            ctype = e.headers.get("Content-Type") if e.headers else ""
            return raw, int(e.code), current, str(ctype or "")
        except Exception:
            return b"", 599, current, ""

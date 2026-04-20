"""Host-level denylist for low-signal, tracking, or commonly abusive destinations (compliance-oriented)."""

from __future__ import annotations

import re
from urllib.parse import urlparse

# Suffixes (lowercased) — block subdomains too.
_BLOCKED_HOST_SUFFIXES: frozenset[str] = frozenset(
    {
        # Social / engagement traps (often thin for factual research)
        "facebook.com",
        "fb.com",
        "instagram.com",
        "tiktok.com",
        "pinterest.com",
        "reddit.com",
        "snapchat.com",
        "t.co",
        "twitter.com",
        "x.com",
        "linkedin.com",
        # Link shorteners (obscure final destination; policy risk)
        "bit.ly",
        "goo.gl",
        "ow.ly",
        "tinyurl.com",
        "t.ly",
        "buff.ly",
        "adf.ly",
        "rebrand.ly",
        # Ad / tracking
        "doubleclick.net",
        "googleadservices.com",
        "googlesyndication.com",
        # Common bot-check / interstitial hosts (scraping often illegal or unstable)
        "hcaptcha.com",
        "recaptcha.net",
        "gstatic.com",
    }
)

# Exact hostnames (lowercase)
_BLOCKED_HOST_EXACT: frozenset[str] = frozenset(
    {
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
    }
)

_IP_HOST = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")


def normalized_host(url: str) -> str | None:
    if not isinstance(url, str) or not url.strip():
        return None
    try:
        p = urlparse(url.strip())
    except Exception:
        return None
    host = (p.hostname or "").lower().strip()
    return host or None


def is_blocked_url(url: str) -> bool:
    host = normalized_host(url)
    if not host:
        return True
    if host in _BLOCKED_HOST_EXACT:
        return True
    if _IP_HOST.match(host):
        return True
    for suffix in _BLOCKED_HOST_SUFFIXES:
        if host == suffix or host.endswith("." + suffix):
            return True
    return False


def filter_results(results: list[dict], *, limit: int) -> list[dict]:
    """Keep first ``limit`` items whose ``url`` is not blocked."""
    out: list[dict] = []
    for r in results:
        if not isinstance(r, dict):
            continue
        u = r.get("url")
        if not isinstance(u, str) or not u.strip():
            continue
        if is_blocked_url(u.strip()):
            continue
        out.append(r)
        if len(out) >= limit:
            break
    return out

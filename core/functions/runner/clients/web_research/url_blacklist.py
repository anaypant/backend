"""
URL blocklist for the in-house web research pipeline.

Categories:
  SOCIAL        — social platforms (thin content, auth walls, infinite scroll)
  SHORTENER     — link shorteners (destination unknown)
  AD_TRACKING   — ad networks and tracking pixels
  AUTH_REQUIRED — login/account walls (would always return gate page)
  PAYWALL       — heavy paywall news (scrape yields <200 chars of useful text)
  PEOPLE_SEARCH — people-finder spam sites (irrelevant, often malicious)
  LOW_SIGNAL    — known low-text / bot-detection / commerce-only domains
  BOT_CHECK     — CAPTCHA / interstitial infrastructure
  INTERNAL      — localhost / private ranges

Blocking is suffix-based so sub.domain.com is blocked when domain.com is listed.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

# ── SOCIAL ───────────────────────────────────────────────────────────────────
_SOCIAL = frozenset({
    "facebook.com", "fb.com", "fbcdn.net",
    "instagram.com", "cdninstagram.com",
    "twitter.com", "x.com", "t.co",
    "linkedin.com", "licdn.com",
    "tiktok.com", "tiktokcdn.com",
    "pinterest.com", "pinimg.com",
    "reddit.com", "redd.it", "redditstatic.com",
    "snapchat.com",
    "tumblr.com",
    "discord.com", "discord.gg",
    "telegram.org", "t.me",
    "whatsapp.com",
    "threads.net",
    "mastodon.social",
})

# ── LINK SHORTENERS ───────────────────────────────────────────────────────────
_SHORTENERS = frozenset({
    "bit.ly", "goo.gl", "ow.ly", "tinyurl.com",
    "t.ly", "buff.ly", "adf.ly", "rebrand.ly",
    "short.io", "rb.gy", "cutt.ly", "is.gd",
    "lnkd.in", "shorturl.at", "tiny.cc",
})

# ── AD / TRACKING ─────────────────────────────────────────────────────────────
_AD_TRACKING = frozenset({
    "doubleclick.net", "googleadservices.com", "googlesyndication.com",
    "adnxs.com", "rubiconproject.com", "criteo.com",
    "taboola.com", "outbrain.com", "mgid.com",
    "scorecardresearch.com", "comscore.com",
    "amplitude.com", "mixpanel.com", "segment.com",
    "hubspot.com",  # marketing-heavy, blocks scraping
    "marketo.com",
})

# ── REQUIRES AUTH ─────────────────────────────────────────────────────────────
_AUTH_REQUIRED = frozenset({
    "mail.google.com", "calendar.google.com",
    "drive.google.com", "docs.google.com", "sheets.google.com",
    "outlook.live.com", "outlook.office.com",
    "mail.yahoo.com",
    "dropbox.com",
    "box.com",
    "notion.so",
    "slack.com",
    "salesforce.com",
    "app.hubspot.com",
})

# ── PAYWALL / HARD GATE ───────────────────────────────────────────────────────
# Sites that consistently return a paywall with < 200 chars of extractable text.
# Note: we leave zillow, trulia, realtor.com, etc. UN-blocked — they're valuable
# for real estate enrichment and their public pages are scrapeable.
_PAYWALL = frozenset({
    "wsj.com", "ft.com",
    "economist.com", "hbr.org",
    "thedeal.com", "pehub.com",
    "law360.com",
    # Medium is partially paywalled and often auth-gates articles
    "medium.com",
    # Quora requires login for most content
    "quora.com",
})

# ── PEOPLE-SEARCH SPAM ────────────────────────────────────────────────────────
# People-finder sites. They're rarely useful for enriching a real estate CRM
# contact, and often show malicious/inaccurate info or require paid registration.
_PEOPLE_SEARCH = frozenset({
    "spokeo.com", "whitepages.com", "peoplefinders.com",
    "intelius.com", "beenverified.com", "mylife.com",
    "instantcheckmate.com", "truthfinder.com", "radaris.com",
    "fastpeoplesearch.com", "411.com", "truepeoplesearch.com",
    "usphonebook.com", "nuwber.com", "zabasearch.com",
    "pipl.com",
})

# ── LOW-SIGNAL DOMAINS ────────────────────────────────────────────────────────
_LOW_SIGNAL = frozenset({
    # Google News relay URLs (CBMi... redirect links from RSS feed).
    # These relay through Google and can't be reliably scraped for text content.
    "news.google.com",
    # Pure video — no extractable text
    "youtube.com", "youtu.be", "vimeo.com", "dailymotion.com",
    "twitch.tv", "loom.com",
    # Pure commerce — not useful for person enrichment
    "amazon.com", "amazon.co.uk", "amazon.ca", "ebay.com", "etsy.com",
    "walmart.com", "target.com", "bestbuy.com",
    "aliexpress.com", "alibaba.com",
    # App stores / developer portals
    "apps.apple.com", "play.google.com",
    "github.com", "gitlab.com", "bitbucket.org",  # code, not person info
    "stackoverflow.com", "stackexchange.com",
    # File storage
    "docs.google.com", "onedrive.live.com", "icloud.com",
    # Aggregation/listing spam
    "yellowpages.com", "yelp.com",  # often thin, auth-gated reviews
    "glassdoor.com",  # requires auth for most content
    "indeed.com", "ziprecruiter.com", "monster.com",
    # Copyright/legal databases (require subscription)
    "law.cornell.edu",  # actually public — leave off this list
    "pacer.gov",        # requires auth
})

# ── BOT-CHECK INFRASTRUCTURE ──────────────────────────────────────────────────
_BOT_CHECK = frozenset({
    "hcaptcha.com", "recaptcha.net", "gstatic.com",
    "cloudflare.com",  # challenge pages
    "imperva.com", "incapsula.com",
})

# ── INTERNAL / LOOPBACK ───────────────────────────────────────────────────────
_INTERNAL_EXACT = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "::1"})

_IP_HOST_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")

# Combined suffix set
_BLOCKED_SUFFIXES: frozenset[str] = (
    _SOCIAL | _SHORTENERS | _AD_TRACKING | _AUTH_REQUIRED |
    _PAYWALL | _PEOPLE_SEARCH | _LOW_SIGNAL | _BOT_CHECK
)


# ── Path-level blocks ─────────────────────────────────────────────────────────
# Some otherwise-good domains have paths that always require auth or are useless.
_BLOCKED_PATH_PREFIXES: tuple[tuple[str, str], ...] = (
    # e.g. google.com/search or maps
    ("google.com", "/maps"),
    ("google.com", "/search"),
    ("nytimes.com", "/subscription"),
    ("bloomberg.com", "/opinion"),    # always paywalled
)


def normalized_host(url: str) -> str | None:
    if not isinstance(url, str) or not url.strip():
        return None
    try:
        p = urlparse(url.strip())
    except Exception:
        return None
    host = (p.hostname or "").lower().strip()
    return host if host else None


def is_blocked_url(url: str) -> bool:
    host = normalized_host(url)
    if not host:
        return True
    if host in _INTERNAL_EXACT:
        return True
    if _IP_HOST_RE.match(host):
        return True
    for suffix in _BLOCKED_SUFFIXES:
        if host == suffix or host.endswith("." + suffix):
            return True
    # Path-level checks
    try:
        p = urlparse(url.strip())
        path = (p.path or "").lower()
        # Normalise host for path check (strip www.)
        base = host.removeprefix("www.")
        for blocked_host, blocked_path in _BLOCKED_PATH_PREFIXES:
            if (base == blocked_host or base.endswith("." + blocked_host)) and path.startswith(blocked_path):
                return True
    except Exception:
        pass
    return False


def filter_results(results: list[dict], *, limit: int) -> list[dict]:
    """Keep first ``limit`` items whose ``url`` passes the blocklist."""
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

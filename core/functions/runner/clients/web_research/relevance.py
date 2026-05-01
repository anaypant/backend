"""
Relevance scoring and content quality filtering for scraped web pages.

Filters happen in two stages:
  1. quality_check()   — fast reject: login walls, error pages, captchas, too-short
  2. score_relevance() — 0.0–1.0 score based on query-term presence and density

Pages that pass quality_check() but score below RELEVANCE_THRESHOLD are dropped
before being sent to the LLM, keeping the context window clean.

Env vars:
  ACS_RELEVANCE_MIN_TEXT_CHARS  default 200  — skip pages shorter than this
  ACS_RELEVANCE_THRESHOLD       default 0.15 — drop pages below this score
"""

from __future__ import annotations

import os
import re
from typing import Any


# ── Config ────────────────────────────────────────────────────────────────────

def _env_int(name: str, default: int) -> int:
    try:
        return int((os.environ.get(name) or "").strip() or default)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float((os.environ.get(name) or "").strip() or default)
    except ValueError:
        return default


MIN_TEXT_CHARS  = _env_int("ACS_RELEVANCE_MIN_TEXT_CHARS", 200)
RELEVANCE_THRESHOLD = _env_float("ACS_RELEVANCE_THRESHOLD", 0.15)

# Stop-words excluded from query term extraction
_STOP_WORDS: frozenset[str] = frozenset({
    "the", "and", "for", "are", "was", "were", "this", "that", "with", "from",
    "have", "not", "but", "all", "can", "its", "one", "has", "who", "what",
    "when", "where", "how", "why", "more", "also", "into", "than", "then",
    "they", "them", "his", "her", "our", "your", "their", "been",
    # Common real-estate query words (too generic to discriminate relevance)
    "real", "estate", "property", "house", "home", "buyer", "seller",
})

# Phrases that strongly suggest a login / paywall page with thin content
_LOGIN_WALL_PHRASES = (
    "sign in to continue",
    "log in to read",
    "log in to view",
    "create an account to",
    "subscribe to read",
    "subscribe to view",
    "subscribe to continue",
    "unlock this article",
    "members only",
    "please log in",
    "you must be logged in",
    "this content is for subscribers",
    "register to access",
    "free trial",         # common on paywall gates
    "sign up to see",
    "get full access",
)

# Phrases that strongly suggest an error page
_ERROR_PAGE_PHRASES = (
    "page not found",
    "404 not found",
    "error 404",
    "this page doesn't exist",
    "this page could not be found",
    "we couldn't find that page",
    "the page you requested was not found",
    "oops! something went wrong",
)

# Bot-detection signals
_BOT_PHRASES = (
    "please complete the security check",
    "prove you are not a robot",
    "enable javascript to continue",
    "javascript is required",
    "verify you are human",
    "ddos protection by",
    "ray id:",   # Cloudflare
    "just a moment",  # Cloudflare JS challenge
    "security | cloudflare",
)


# ── Quality check ─────────────────────────────────────────────────────────────

def quality_check(text: str, url: str = "") -> tuple[bool, str]:
    """
    Return ``(passes, reason)``.

    ``passes=False`` means the page should be discarded before relevance scoring.
    ``reason`` is a short machine-readable code for audit logs.
    """
    if not isinstance(text, str):
        return False, "not_string"

    stripped = text.strip()
    n = len(stripped)

    if n < MIN_TEXT_CHARS:
        return False, f"too_short_{n}"

    low = stripped.lower()

    # Bot / CAPTCHA page
    for phrase in _BOT_PHRASES:
        if phrase in low and n < 3000:
            return False, "bot_check_page"

    # Login / paywall gate — only flag when content is thin (< 2 KB)
    if n < 2000:
        for phrase in _LOGIN_WALL_PHRASES:
            if phrase in low:
                return False, "login_wall"

    # Error page — flag when content is thin (< 1 KB)
    if n < 1000:
        for phrase in _ERROR_PAGE_PHRASES:
            if phrase in low:
                return False, "error_page"

    return True, "ok"


# ── Query term extractor ──────────────────────────────────────────────────────

def extract_query_terms(query: str) -> list[str]:
    """
    Return meaningful words from ``query`` for relevance scoring.
    Removes stop-words and short tokens.
    """
    words = re.findall(r"\b[a-zA-Z]{3,}\b", query)
    return [w.lower() for w in words if w.lower() not in _STOP_WORDS]


# ── Relevance scorer ──────────────────────────────────────────────────────────

def score_relevance(text: str, terms: list[str]) -> float:
    """
    Return a 0.0–1.0 relevance score for a scraped page.

    Score = weighted combination of:
      • coverage  — fraction of query terms that appear at least once (0–1)
      • density   — normalised total hit count scaled to text length (0–1)

    A page mentioning all query terms densely scores near 1.0.
    A page mentioning none scores 0.0.
    """
    if not text or not terms:
        return 0.5 if not terms else 0.0

    low = text.lower()

    # Coverage: how many distinct terms appear
    hits = [t for t in terms if t in low]
    coverage = len(hits) / len(terms)

    # Density: total occurrences normalised to text length
    total_occurrences = sum(low.count(t) for t in hits)
    # Expect ~1 occurrence per 300 chars for "average" relevance
    expected = max(1, len(low) / 300)
    density = min(1.0, total_occurrences / expected)

    # Named-entity bonus: capitalised versions of query terms in title/first 500 chars
    head = text[:500]
    entity_hits = sum(1 for t in terms if t.capitalize() in head or t.upper() in head)
    entity_bonus = min(0.3, entity_hits * 0.1)

    return min(1.0, coverage * 0.55 + density * 0.30 + entity_bonus * 0.15)


# ── Batch filter ─────────────────────────────────────────────────────────────

def filter_scraped(
    scraped: list[dict[str, Any]],
    query: str,
    *,
    threshold: float | None = None,
    max_pages: int = 8,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Filter and score a list of scraped page dicts (from ``scrape.py``).

    Returns ``(kept, rejected)`` where each item in ``kept`` has an added
    ``_relevance`` float field.

    Filtering order:
      1. ok=False pages (failed HTTP fetch) → rejected
      2. quality_check fails (login wall, error page, too short) → rejected
      3. score_relevance < threshold → rejected
      4. Remaining sorted by relevance descending, capped at max_pages
    """
    thr = threshold if threshold is not None else RELEVANCE_THRESHOLD
    terms = extract_query_terms(query)

    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for page in scraped:
        if not isinstance(page, dict):
            continue

        if not page.get("ok"):
            page["_reject_reason"] = "http_failed"
            rejected.append(page)
            continue

        text = page.get("text") or ""
        url  = page.get("url") or ""

        passes, reason = quality_check(text, url)
        if not passes:
            page["_reject_reason"] = reason
            rejected.append(page)
            continue

        score = score_relevance(text, terms)
        page["_relevance"] = round(score, 3)

        if score < thr:
            page["_reject_reason"] = f"low_relevance_{score:.2f}"
            rejected.append(page)
            continue

        kept.append(page)

    # Sort by relevance descending, cap at max_pages
    kept.sort(key=lambda p: p.get("_relevance") or 0.0, reverse=True)
    if len(kept) > max_pages:
        for page in kept[max_pages:]:
            page["_reject_reason"] = "cap_exceeded"
            rejected.append(page)
        kept = kept[:max_pages]

    return kept, rejected

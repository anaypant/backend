"""
In-house web search — zero external API cost.

Three free backends fan out concurrently:
  1. DuckDuckGo HTML  (html.duckduckgo.com/html/) — general web, text-browser interface
  2. Wikipedia API    (en.wikipedia.org/w/api.php) — factual/biographical sources
  3. Google News RSS  (news.google.com/rss/search) — recent news without auth

``search_top_results(query, fetch_count=N)`` selects the backend via
``ACS_WEB_SEARCH_BACKEND`` env var:
  - ``duckduckgo``  — only DDG (fastest)
  - ``multi``       — DDG + Wikipedia + Google News RSS concurrently (most sources)
  - ``brave``       — paid Brave Search API (requires BRAVE_SEARCH_API_KEY)
  - ``tavily``      — paid Tavily API (requires TAVILY_API_KEY)
  - ``none``        — no search; pipeline falls back to LLM-only

Paid backends are kept as fallback options.
"""

from __future__ import annotations

import gzip
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from typing import Any


# ── HTTP helpers ─────────────────────────────────────────────────────────────

def _http_get(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: int = 20,
    data: bytes | None = None,
) -> tuple[bytes, int]:
    """Minimal HTTP GET/POST returning (body_bytes, status). Never raises."""
    h: dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "close",
    }
    if headers:
        h.update(headers)
    method = "POST" if data is not None else "GET"
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(2_000_000)
            encoding = (resp.headers.get("Content-Encoding") or "").lower()
            raw = _decompress(raw, encoding)
            return raw, int(resp.status)
    except urllib.error.HTTPError as e:
        try:
            raw = e.read(200_000)
        except Exception:
            raw = b""
        return raw, int(e.code)
    except Exception:
        return b"", 599


def _decompress(raw: bytes, encoding: str) -> bytes:
    if not raw or encoding in ("identity", ""):
        return raw
    if "gzip" in encoding:
        try:
            return gzip.decompress(raw)
        except Exception:
            return raw
    if "deflate" in encoding:
        try:
            return zlib.decompress(raw)
        except Exception:
            try:
                return zlib.decompress(raw, -zlib.MAX_WBITS)
            except Exception:
                return raw
    return raw


def _decode_text(raw: bytes) -> str:
    for enc in ("utf-8", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


# ── DuckDuckGo HTML scraper ───────────────────────────────────────────────────

def _decode_ddg_redirect(href: str) -> str:
    """
    DDG wraps result URLs in /l/?uddg=<encoded_url>&...
    Extract and decode the real destination.
    """
    if not href:
        return ""
    if href.startswith("/l/?") or "/l/?" in href:
        try:
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
            uddg = qs.get("uddg", [""])[0]
            if uddg:
                return urllib.parse.unquote(uddg)
        except Exception:
            pass
    if href.startswith("http"):
        return href
    return ""


class _DDGParser(HTMLParser):
    """
    Parse DuckDuckGo's HTML results page.

    DDG HTML structure:
      <div class="result__body">
        <h2 class="result__title">
          <a class="result__a" href="/l/?uddg=ENCODED_URL&...">Title</a>
        </h2>
        <a class="result__snippet" href="...">Snippet text</a>
      </div>
    """

    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._depth = 0
        self._result_depth: int | None = None
        self._cur: dict[str, str] | None = None
        self._capture: str | None = None  # "title" | "snippet"

    def handle_starttag(self, tag: str, attrs: list) -> None:
        self._depth += 1
        d = {k: v or "" for k, v in attrs}
        cls = d.get("class") or ""

        if "result__body" in cls and tag == "div":
            self._result_depth = self._depth
            self._cur = {"url": "", "title": "", "snippet": ""}
            return

        if self._cur is None:
            return

        if tag == "a" and "result__a" in cls:
            href = _decode_ddg_redirect(d.get("href") or "")
            if href:
                self._cur["url"] = href
            self._capture = "title"
            return

        if tag == "a" and "result__snippet" in cls:
            self._capture = "snippet"

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self._capture = None
        if tag == "div" and self._depth == self._result_depth:
            if self._cur and self._cur.get("url", "").startswith("http"):
                self.results.append(dict(self._cur))
            self._cur = None
            self._result_depth = None
            self._capture = None
        self._depth -= 1

    def handle_data(self, data: str) -> None:
        if self._capture == "title" and self._cur is not None:
            self._cur["title"] = (self._cur.get("title") or "") + data
        elif self._capture == "snippet" and self._cur is not None:
            self._cur["snippet"] = (self._cur.get("snippet") or "") + data


def search_duckduckgo(query: str, *, count: int) -> list[dict[str, Any]]:
    """
    Scrape DuckDuckGo's text-browser HTML endpoint.

    Uses POST to html.duckduckgo.com/html/ — the endpoint designed for non-JS clients,
    stable and ToS-friendly for low-volume programmatic use.
    """
    q = urllib.parse.urlencode({"q": query, "kl": "us-en", "kp": "-1"}).encode("utf-8")
    raw, st = _http_get(
        "https://html.duckduckgo.com/html/",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=25,
        data=q,
    )
    if st >= 400 or not raw:
        return []
    html = _decode_text(raw)
    parser = _DDGParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for r in parser.results:
        url = (r.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        out.append({
            "url": url,
            "title": (r.get("title") or "").strip()[:500],
            "snippet": (r.get("snippet") or "").strip()[:2000],
        })
        if len(out) >= count:
            break
    return out


# ── Wikipedia API ─────────────────────────────────────────────────────────────

def search_wikipedia(query: str, *, count: int) -> list[dict[str, Any]]:
    """
    Wikipedia OpenSearch + Extracts API.
    Returns up to ``count`` articles with title, URL, and intro extract as snippet.
    Always free, no auth.
    """
    # Step 1: find matching article titles
    search_url = (
        "https://en.wikipedia.org/w/api.php?"
        + urllib.parse.urlencode({
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": min(count, 5),
            "srnamespace": 0,
            "format": "json",
            "utf8": 1,
        })
    )
    raw, st = _http_get(
        search_url,
        headers={"Accept": "application/json"},
        timeout=15,
    )
    if st >= 400 or not raw:
        return []
    try:
        data = json.loads(_decode_text(raw))
    except Exception:
        return []

    hits = data.get("query", {}).get("search") or []
    if not hits:
        return []

    titles = [h["title"] for h in hits if isinstance(h, dict) and h.get("title")][:count]
    if not titles:
        return []

    # Step 2: fetch intro extracts for all titles in one request
    extract_url = (
        "https://en.wikipedia.org/w/api.php?"
        + urllib.parse.urlencode({
            "action": "query",
            "prop": "extracts",
            "exintro": 1,
            "explaintext": 1,
            "titles": "|".join(titles),
            "format": "json",
            "utf8": 1,
            "redirects": 1,
        })
    )
    raw2, st2 = _http_get(
        extract_url,
        headers={"Accept": "application/json"},
        timeout=15,
    )
    extracts: dict[str, str] = {}
    if st2 < 400 and raw2:
        try:
            ed = json.loads(_decode_text(raw2))
            pages = ed.get("query", {}).get("pages") or {}
            for page in pages.values():
                if isinstance(page, dict) and page.get("title"):
                    extracts[page["title"]] = (page.get("extract") or "")[:3000]
        except Exception:
            pass

    out: list[dict[str, Any]] = []
    for title in titles:
        url = "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))
        snippet = extracts.get(title) or ""
        # Strip blank lines and truncate for snippet
        snippet = re.sub(r"\n{2,}", " ", snippet).strip()[:2000]
        out.append({"url": url, "title": title[:500], "snippet": snippet})
    return out


# ── Google News RSS ───────────────────────────────────────────────────────────

def search_google_news_rss(query: str, *, count: int) -> list[dict[str, Any]]:
    """
    Google News RSS feed — free, no auth, recent news only.
    Note: Google News wraps article URLs in redirect links; we extract the actual URL from the redirect.
    """
    feed_url = (
        "https://news.google.com/rss/search?"
        + urllib.parse.urlencode({
            "q": query,
            "hl": "en-US",
            "gl": "US",
            "ceid": "US:en",
        })
    )
    raw, st = _http_get(feed_url, timeout=15)
    if st >= 400 or not raw:
        return []
    try:
        root = ET.fromstring(_decode_text(raw))
    except ET.ParseError:
        return []

    ns = ""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    for item in root.iter("item"):
        title_el = item.find("title")
        link_el = item.find("link")
        desc_el = item.find("description")
        if link_el is None:
            continue
        url = (link_el.text or "").strip()
        if not url or url in seen:
            continue
        # Google News link is the article source URL directly in most feeds
        # but can be a redirect — strip HTML tags from description
        snippet = re.sub(r"<[^>]+>", " ", desc_el.text or "") if desc_el is not None else ""
        snippet = re.sub(r"\s+", " ", snippet).strip()[:2000]
        title = (title_el.text or "").strip()[:500]
        # Strip the source name that Google appends (e.g. "Title - Reuters")
        if " - " in title:
            title = title.rsplit(" - ", 1)[0].strip()
        seen.add(url)
        out.append({"url": url, "title": title, "snippet": snippet})
        if len(out) >= count:
            break
    return out


# ── Multi-source fan-out ──────────────────────────────────────────────────────

def _dedup_by_domain(results: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """
    Keep max 2 results per domain, preserve overall ordering.
    Prioritises DuckDuckGo results first since they have the broadest coverage.
    """
    from urllib.parse import urlparse
    domain_count: dict[str, int] = {}
    out: list[dict[str, Any]] = []
    for r in results:
        try:
            host = urlparse(r.get("url") or "").hostname or ""
            # Normalise: strip www.
            host = re.sub(r"^www\.", "", host.lower())
        except Exception:
            host = ""
        if domain_count.get(host, 0) >= 2:
            continue
        domain_count[host] = domain_count.get(host, 0) + 1
        out.append(r)
        if len(out) >= limit:
            break
    return out


def search_multi_free(query: str, *, count: int) -> list[dict[str, Any]]:
    """
    Fan out to DuckDuckGo + Wikipedia + Google News concurrently.
    Deduplicates by domain, returning up to ``count`` URLs.
    """
    ddg_n   = max(count, count + 5)   # fetch extra to survive blacklist filtering
    wiki_n  = min(3, count)
    news_n  = min(4, count)

    tasks = [
        ("ddg",   lambda: search_duckduckgo(query, count=ddg_n)),
        ("wiki",  lambda: search_wikipedia(query, count=wiki_n)),
        ("news",  lambda: search_google_news_rss(query, count=news_n)),
    ]

    bucket: dict[str, list[dict[str, Any]]] = {k: [] for k, _ in tasks}
    with ThreadPoolExecutor(max_workers=3) as pool:
        futs = {pool.submit(fn): name for name, fn in tasks}
        for fut in as_completed(futs, timeout=30):
            name = futs[fut]
            try:
                bucket[name] = fut.result() or []
            except Exception:
                bucket[name] = []

    # Merge: DDG first (most general), then News (recency), then Wikipedia (authoritative)
    merged = bucket["ddg"] + bucket["news"] + bucket["wiki"]
    return _dedup_by_domain(merged, limit=count)


# ── Paid backends (kept as optional) ─────────────────────────────────────────

def search_brave(query: str, *, count: int) -> list[dict[str, Any]]:
    key = (os.environ.get("BRAVE_SEARCH_API_KEY") or "").strip()
    if not key:
        return []
    q = urllib.parse.quote_plus(query)
    url = f"https://api.search.brave.com/res/v1/web/search?q={q}&count={min(count, 20)}"
    raw, st = _http_get(
        url,
        headers={"X-Subscription-Token": key, "Accept": "application/json"},
        timeout=30,
    )
    if st >= 400 or not raw:
        return []
    try:
        body = json.loads(_decode_text(raw))
    except Exception:
        return []
    results = (body.get("web") or {}).get("results") or []
    out: list[dict[str, Any]] = []
    for r in results:
        if not isinstance(r, dict):
            continue
        u = r.get("url")
        if not isinstance(u, str) or not u.strip():
            continue
        out.append({
            "url": u.strip(),
            "title": str(r.get("title") or "")[:500],
            "snippet": str(r.get("description") or "")[:2000],
        })
    return out


def search_tavily(query: str, *, count: int) -> list[dict[str, Any]]:
    key = (os.environ.get("TAVILY_API_KEY") or "").strip()
    if not key:
        return []
    body_bytes = json.dumps({
        "api_key": key,
        "query": query,
        "max_results": min(count, 20),
        "search_depth": "basic",
    }).encode("utf-8")
    raw, st = _http_get(
        "https://api.tavily.com/search",
        headers={"Content-Type": "application/json"},
        timeout=45,
        data=body_bytes,
    )
    if st >= 400 or not raw:
        return []
    try:
        body = json.loads(_decode_text(raw))
    except Exception:
        return []
    results = body.get("results") or []
    out: list[dict[str, Any]] = []
    for r in results:
        if not isinstance(r, dict):
            continue
        u = r.get("url")
        if not isinstance(u, str) or not u.strip():
            continue
        out.append({
            "url": u.strip(),
            "title": str(r.get("title") or "")[:500],
            "snippet": str(r.get("content") or "")[:2000],
        })
    return out


# ── Entrypoint ────────────────────────────────────────────────────────────────

def search_top_results(query: str, *, fetch_count: int) -> tuple[list[dict[str, Any]], str]:
    """
    Return ``(results, backend_id)``.

    ``ACS_WEB_SEARCH_BACKEND``:
      ``duckduckgo`` (default) — free, in-house DDG HTML scraping.
                                 Auto-falls back to Wikipedia + Google News when DDG
                                 returns 0 results (rate-limit / no-match recovery).
      ``multi``                — DDG + Wikipedia + Google News concurrently (most sources)
      ``brave``                — paid Brave Search API
      ``tavily``               — paid Tavily API
      ``none``                 — disabled; pipeline falls back to LLM-only
    """
    backend = (os.environ.get("ACS_WEB_SEARCH_BACKEND") or "duckduckgo").strip().lower()

    if backend == "duckduckgo":
        results = search_duckduckgo(query, count=fetch_count)
        if results:
            return results, "duckduckgo"
        # DDG returned 0 — rate-limit or no matches.  Fall back to Wikipedia + Google News
        # which have separate rate limits and handle generic queries well.
        fallback = search_wikipedia(query, count=3) + search_google_news_rss(query, count=4)
        seen: set[str] = set()
        deduped = [r for r in fallback if r.get("url") and not seen.add(r["url"])]  # type: ignore[func-returns-value]
        return deduped[:fetch_count], "duckduckgo_fallback"

    if backend == "multi":
        return search_multi_free(query, count=fetch_count), "multi"
    if backend == "brave":
        return search_brave(query, count=fetch_count), "brave"
    if backend == "tavily":
        return search_tavily(query, count=fetch_count), "tavily"
    # "none" or unrecognised
    return [], "none"

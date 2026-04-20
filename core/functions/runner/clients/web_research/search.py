"""Search backends that return ranked URL results (API-first, ToS-respecting)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


def _post_json(url: str, payload: dict, headers: dict[str, str], *, timeout: int) -> tuple[dict, int]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={**headers, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(2_000_000)
            st = int(resp.status)
    except urllib.error.HTTPError as e:
        raw = e.read(200_000)
        st = int(e.code)
    except Exception:
        return {"error": "request_failed"}, 599
    try:
        return json.loads(raw.decode("utf-8", errors="replace")), st
    except json.JSONDecodeError:
        return {"error": "invalid_json", "raw": raw[:500].decode("utf-8", errors="replace")}, st


def _get_json(url: str, headers: dict[str, str], *, timeout: int) -> tuple[dict, int]:
    req = urllib.request.Request(url, method="GET", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(2_000_000)
            st = int(resp.status)
    except urllib.error.HTTPError as e:
        raw = e.read(200_000)
        st = int(e.code)
    except Exception:
        return {"error": "request_failed"}, 599
    try:
        return json.loads(raw.decode("utf-8", errors="replace")), st
    except json.JSONDecodeError:
        return {"error": "invalid_json"}, st


def search_brave(query: str, *, count: int) -> list[dict[str, Any]]:
    key = (os.environ.get("BRAVE_SEARCH_API_KEY") or "").strip()
    if not key:
        return []
    q = urllib.parse.quote_plus(query)
    url = f"https://api.search.brave.com/res/v1/web/search?q={q}&count={min(count, 20)}"
    headers = {"X-Subscription-Token": key, "Accept": "application/json"}
    body, st = _get_json(url, headers, timeout=30)
    if st >= 400:
        return []
    web = body.get("web") if isinstance(body.get("web"), dict) else {}
    results = web.get("results")
    out: list[dict[str, Any]] = []
    if not isinstance(results, list):
        return out
    for r in results:
        if not isinstance(r, dict):
            continue
        u = r.get("url")
        if not isinstance(u, str) or not u.strip():
            continue
        title = r.get("title") if isinstance(r.get("title"), str) else ""
        desc = r.get("description") if isinstance(r.get("description"), str) else ""
        out.append({"url": u.strip(), "title": title[:500], "snippet": desc[:2000]})
    return out


def search_tavily(query: str, *, count: int) -> list[dict[str, Any]]:
    key = (os.environ.get("TAVILY_API_KEY") or "").strip()
    if not key:
        return []
    payload = {
        "api_key": key,
        "query": query,
        "max_results": min(count, 20),
        "search_depth": "basic",
    }
    body, st = _post_json("https://api.tavily.com/search", payload, {}, timeout=45)
    if st >= 400:
        return []
    results = body.get("results")
    out: list[dict[str, Any]] = []
    if not isinstance(results, list):
        return out
    for r in results:
        if not isinstance(r, dict):
            continue
        u = r.get("url")
        if not isinstance(u, str) or not u.strip():
            continue
        title = r.get("title") if isinstance(r.get("title"), str) else ""
        content = r.get("content") if isinstance(r.get("content"), str) else ""
        out.append({"url": u.strip(), "title": title[:500], "snippet": content[:2000]})
    return out


def search_top_results(query: str, *, fetch_count: int) -> tuple[list[dict[str, Any]], str]:
    """
    Return ``(results, backend_id)``.

    ``ACS_WEB_SEARCH_BACKEND`` = ``brave`` | ``tavily`` | ``none`` (default ``none``).
    """
    backend = (os.environ.get("ACS_WEB_SEARCH_BACKEND") or "none").strip().lower()
    if backend == "brave":
        return search_brave(query, count=fetch_count), "brave"
    if backend == "tavily":
        return search_tavily(query, count=fetch_count), "tavily"
    return [], "none"

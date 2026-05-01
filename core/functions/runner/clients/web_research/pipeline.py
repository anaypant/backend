"""
In-house web research pipeline.

Flow:
  1. search_top_results()     — DuckDuckGo HTML / Wikipedia / Google News RSS (or paid backend)
  2. filter_results()         — host-level blocklist
  3. scrape_many_concurrent() — browser-like concurrent fetch
  4. filter_scraped()         — quality check + relevance scoring, drops thin/irrelevant pages
  5. LLM coalescion           — factual summary + structured sources

Backend is selected by ACS_WEB_SEARCH_BACKEND (default: duckduckgo).
If no URLs survive steps 1–3, the pipeline falls back to LLM-only mode.
"""

from __future__ import annotations

import json
import os
from typing import Any

from clients import llm_internal
from clients.web_research.browser_fetch import BrowserFetchSession
from clients.web_research.relevance import filter_scraped
from clients.web_research.sanitize import sanitize_page_text
from clients.web_research.scrape import scrape_many_concurrent
from clients.web_research.search import search_top_results
from clients.web_research.url_blacklist import filter_results


def _default_provider() -> str:
    return (os.environ.get("ACS_ENRICHMENT_LLM_PROVIDER") or "openrouter").strip() or "openrouter"


def _default_model() -> str:
    return (os.environ.get("ACS_ENRICHMENT_LLM_MODEL") or "openai/gpt-4o-mini").strip() or "openai/gpt-4o-mini"


def _coalesce_scraped(query: str, scraped: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    parts.append(f"User query:\n{query.strip()}\n")
    parts.append("--- Scraped pages (relevance score, title, URL, plain text) ---\n")
    for i, row in enumerate(scraped, start=1):
        if not isinstance(row, dict):
            continue
        title = row.get("title") or ""
        url = row.get("final_url") or row.get("url") or ""
        rel = row.get("_relevance")
        rel_str = f" rel={rel:.2f}" if rel is not None else ""
        text = row.get("text") if isinstance(row.get("text"), str) else ""
        text = sanitize_page_text(text, max_chars=12_000)
        parts.append(f"[{i}]{rel_str} title={title}\nurl={url}\n{text}\n")
    raw = "\n".join(parts)
    return sanitize_page_text(raw, max_chars=100_000)


def _llm_call(
    messages: list[dict],
    *,
    provider: str,
    model: str,
) -> tuple[dict[str, Any], int, int]:
    """
    Call the LLM and parse the JSON response.
    Returns ``(payload_dict, http_status, llm_calls)``.
    ``payload_dict`` always has ``summary`` and ``sources`` keys.
    """
    try:
        body, st = llm_internal.complete(
            model=model,
            messages=messages,
            provider=provider,
            response_format="json",
        )
    except Exception as e:
        return {"summary": "", "sources": [], "error": str(e)}, 503, 1

    raw_text = body.get("text") if isinstance(body.get("text"), str) else ""
    if st >= 400:
        return {"summary": "", "sources": [], "detail": body}, st, 1

    summary = ""
    sources: list[dict[str, str]] = []
    try:
        parsed = json.loads(raw_text) if raw_text.strip() else {}
        if isinstance(parsed, dict):
            if isinstance(parsed.get("summary"), str):
                summary = parsed["summary"].strip()
            src = parsed.get("sources")
            if isinstance(src, list):
                for item in src:
                    if not isinstance(item, dict):
                        continue
                    sources.append({
                        "title": str(item.get("title") or "")[:500],
                        "url": str(item.get("url") or "")[:2000],
                        "snippet": str(item.get("snippet") or "")[:4000],
                    })
    except json.JSONDecodeError:
        summary = raw_text.strip()[:8000]

    return {"summary": summary, "sources": sources, "llm_status": st}, 200, 1


def run_research_pipeline(
    query: str,
    *,
    result_limit: int,
    provider: str | None = None,
    model: str | None = None,
) -> tuple[dict[str, Any], int]:
    """
    Full in-house web research pipeline.

    1. Search (DuckDuckGo HTML / multi / Brave / Tavily per env).
    2. Apply host blocklist.
    3. Concurrent browser-like scrape.
    4. Relevance filter — drops login walls, error pages, off-topic pages.
    5. LLM synthesis → structured summary + sources.

    Falls back to LLM-only when no URLs survive steps 1–2 (backend unconfigured or zero hits).
    Falls back to best-effort scrape when relevance filter drops every page.

    Returns ``(payload, http_status)`` matching the legacy ``research_query_to_summary`` contract.
    """
    q = query.strip() if isinstance(query, str) else ""
    if not q:
        return {"summary": "", "sources": [], "mode": "empty_query", "llm_calls": 0}, 400

    limit = max(1, min(20, int(result_limit)))
    fetch_pool = min(40, max(limit + 4, limit * 3))

    prov = provider or _default_provider()
    mdl = model or _default_model()

    # ── Step 1–2: search + blacklist ─────────────────────────────────────────
    raw_hits, backend = search_top_results(q, fetch_count=fetch_pool)
    filtered = filter_results(raw_hits, limit=limit + 4)  # +4 buffer for relevance drops

    # ── LLM-only fallback (no search backend / zero results) ─────────────────
    if not filtered:
        schema_llm = (
            "Return JSON only: summary (string, concise factual synthesis from your knowledge), "
            "sources (array of {title, url, snippet}). "
            "Use verifiable public URLs when known; set url to empty string if unsure."
        )
        messages_llm = [{"role": "user", "content": f"{schema_llm}\n\nResearch query: {q}"}]
        result, st, calls = _llm_call(messages_llm, provider=prov, model=mdl)
        if "error" in result:
            return {
                **result,
                "mode": "llm_fallback_error",
                "llm_calls": calls,
                "pipeline": _pipeline_meta(backend, [], [], []),
            }, 503
        return {
            **result,
            "mode": "llm_fallback",
            "llm_calls": calls,
            "llm": {"provider": prov, "model": mdl},
            "pipeline": _pipeline_meta(backend, filtered, [], []),
        }, st

    # ── Step 3: concurrent scrape ─────────────────────────────────────────────
    session = BrowserFetchSession()
    scraped = scrape_many_concurrent(session, filtered)

    # ── Step 4: relevance filter ──────────────────────────────────────────────
    kept, rejected = filter_scraped(scraped, q, max_pages=limit)

    # If relevance filter killed everything, fall back to all scraped pages
    # (quality-check failures are still excluded — they have no real content)
    if not kept:
        kept_fallback = [p for p in scraped if p.get("ok") and (p.get("text") or "")]
        if kept_fallback:
            kept = kept_fallback[:limit]
        else:
            # Truly no content — LLM-only fallback
            schema_llm = (
                "Return JSON only: summary (string, concise factual synthesis from your knowledge), "
                "sources (array of {title, url, snippet}). "
                "Use verifiable public URLs when known."
            )
            messages_llm = [{"role": "user", "content": f"{schema_llm}\n\nResearch query: {q}"}]
            result, st, calls = _llm_call(messages_llm, provider=prov, model=mdl)
            if "error" in result:
                return {
                    **result,
                    "mode": "scrape_empty_llm_fallback_error",
                    "llm_calls": calls,
                    "pipeline": _pipeline_meta(backend, filtered, scraped, rejected),
                }, 503
            return {
                **result,
                "mode": "scrape_empty_llm_fallback",
                "llm_calls": calls,
                "llm": {"provider": prov, "model": mdl},
                "pipeline": _pipeline_meta(backend, filtered, scraped, rejected),
            }, st

    # ── Step 5: LLM synthesis ─────────────────────────────────────────────────
    coalesced = _coalesce_scraped(q, kept)
    schema = (
        "Return JSON only: summary (string, concise factual synthesis), "
        "sources (array of {title, url, snippet} string fields). "
        "Each snippet should reflect the scraped evidence. "
        "Only include sources whose content was actually useful for the summary."
    )
    messages = [{"role": "user", "content": f"{schema}\n\n{coalesced}"[:120_000]}]

    result, st, calls = _llm_call(messages, provider=prov, model=mdl)
    if "error" in result:
        return {
            **result,
            "mode": "pipeline_llm_error",
            "llm_calls": calls,
            "pipeline": _pipeline_meta(backend, filtered, scraped, rejected),
        }, 503

    return {
        **result,
        "mode": "scrape_then_llm",
        "llm_calls": calls,
        "llm": {"provider": prov, "model": mdl},
        "pipeline": _pipeline_meta(backend, filtered, scraped, rejected),
    }, st


def _pipeline_meta(
    backend: str,
    filtered: list[dict[str, Any]],
    scraped: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
) -> dict[str, Any]:
    scrape_ok = sum(1 for s in scraped if isinstance(s, dict) and s.get("ok"))
    render_needed = 0
    render_used = 0
    for s in scraped:
        if not isinstance(s, dict):
            continue
        r = s.get("render")
        if isinstance(r, dict):
            if r.get("needed"):
                render_needed += 1
            if r.get("used"):
                render_used += 1

    # Rejection reason summary
    reasons: dict[str, int] = {}
    for p in rejected:
        reason = p.get("_reject_reason") or "unknown"
        reasons[reason] = reasons.get(reason, 0) + 1

    return {
        "search_backend": backend,
        "urls_after_blacklist": len(filtered),
        "scrape_ok": scrape_ok,
        "scrape_total": len(scraped),
        "relevance_kept": len(scraped) - len(rejected),
        "relevance_rejected": len(rejected),
        "rejection_reasons": reasons,
        "render_needed": render_needed,
        "render_used": render_used,
    }

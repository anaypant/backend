"""Search → blacklist → concurrent scrape → sanitize → LLM coalescence."""

from __future__ import annotations

import json
import os
from typing import Any

from clients import llm_internal
from clients.web_research.browser_fetch import BrowserFetchSession
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
    parts.append("--- Scraped pages (title, URL, plain text) ---\n")
    for i, row in enumerate(scraped, start=1):
        if not isinstance(row, dict):
            continue
        title = row.get("title") or ""
        url = row.get("final_url") or row.get("url") or ""
        ok = row.get("ok")
        text = row.get("text") if isinstance(row.get("text"), str) else ""
        text = sanitize_page_text(text, max_chars=12_000)
        parts.append(f"[{i}] ok={ok} title={title}\nurl={url}\n{text}\n")
    raw = "\n".join(parts)
    return sanitize_page_text(raw, max_chars=100_000)


def run_research_pipeline(
    query: str,
    *,
    result_limit: int,
    provider: str | None = None,
    model: str | None = None,
) -> tuple[dict[str, Any], int]:
    """
    Full procedure:

    1. Search (Brave or Tavily per env) for ``fetch_count`` candidates.
    2. Apply host blacklist; keep first ``result_limit`` URLs.
    3. Fetch each URL concurrently using browser-like headers and pacing.
    4. Strip HTML → text; strip non-ASCII and noisy control characters.
    5. Coalesce and ask the LLM for a factual summary plus structured sources.

    Returns ``(payload, http_status)`` where ``payload`` matches the legacy
    ``research_query_to_summary`` contract plus ``mode`` / ``pipeline`` / ``llm_calls``.
    """
    q = query.strip() if isinstance(query, str) else ""
    if not q:
        return {"summary": "", "sources": [], "mode": "empty_query", "llm_calls": 0}, 400

    limit = max(1, min(20, int(result_limit)))
    fetch_pool = min(30, max(limit, limit * 3))

    raw_hits, backend = search_top_results(q, fetch_count=fetch_pool)
    filtered = filter_results(raw_hits, limit=limit)

    prov = provider or _default_provider()
    mdl = model or _default_model()

    # When the search backend is not configured or returns no usable URLs, fall back to
    # LLM-only mode so the workflow still produces a best-effort summary from model knowledge.
    if not filtered:
        schema_llm = (
            "Return JSON only: summary (string, concise factual synthesis from your knowledge), "
            "sources (array of {title, url, snippet}). "
            "Use verifiable public URLs when known; set url to empty string if unsure."
        )
        messages_llm = [{"role": "user", "content": f"{schema_llm}\n\nResearch query: {q}"}]
        llm_calls = 1
        try:
            body, st = llm_internal.complete(
                model=mdl,
                messages=messages_llm,
                provider=prov,
                response_format="json",
            )
        except Exception as e:
            return {
                "summary": "",
                "sources": [],
                "mode": "llm_fallback_error",
                "llm_calls": llm_calls,
                "error": str(e),
                "pipeline": _pipeline_meta(backend, filtered, []),
            }, 503
        if st >= 400:
            return {
                "summary": "",
                "sources": [],
                "mode": "llm_fallback_upstream",
                "llm_calls": llm_calls,
                "pipeline": _pipeline_meta(backend, filtered, []),
            }, st

        raw_text = body.get("text") if isinstance(body.get("text"), str) else ""
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

        return {
            "summary": summary,
            "sources": sources,
            "mode": "llm_fallback",
            "llm_calls": llm_calls,
            "llm": {"provider": prov, "model": mdl, "http_status": st},
            "pipeline": _pipeline_meta(backend, filtered, []),
        }, 200

    session = BrowserFetchSession()
    scraped = scrape_many_concurrent(session, filtered)

    coalesced = _coalesce_scraped(q, scraped)

    schema = (
        "Return JSON only: summary (string, concise factual synthesis), "
        "sources (array of {title, url, snippet} string fields). "
        "Each snippet should reflect the scraped evidence when possible; otherwise say so briefly."
    )
    messages = [
        {
            "role": "user",
            "content": f"{schema}\n\n{coalesced}"[:120_000],
        }
    ]
    llm_calls = 1
    try:
        body, st = llm_internal.complete(
            model=mdl,
            messages=messages,
            provider=prov,
            response_format="json",
        )
    except Exception as e:
        return {
            "summary": "",
            "sources": [],
            "mode": "pipeline_llm_error",
            "llm_calls": llm_calls,
            "error": str(e),
            "pipeline": _pipeline_meta(backend, filtered, scraped),
        }, 503

    if st >= 400:
        return {
            "summary": "",
            "sources": [],
            "mode": "pipeline_llm_upstream",
            "llm_calls": llm_calls,
            "detail": body,
            "pipeline": _pipeline_meta(backend, filtered, scraped),
        }, st

    raw_text = body.get("text") if isinstance(body.get("text"), str) else ""
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
                    sources.append(
                        {
                            "title": str(item.get("title") or "")[:500],
                            "url": str(item.get("url") or "")[:2000],
                            "snippet": str(item.get("snippet") or "")[:4000],
                        }
                    )
    except json.JSONDecodeError:
        summary = raw_text.strip()[:8000]

    out: dict[str, Any] = {
        "summary": summary,
        "sources": sources,
        "mode": "scrape_then_llm",
        "llm_calls": llm_calls,
        "llm": {"provider": prov, "model": mdl, "http_status": st},
        "pipeline": _pipeline_meta(backend, filtered, scraped),
    }
    return out, 200


def _pipeline_meta(
    backend: str,
    filtered: list[dict[str, Any]],
    scraped: list[dict[str, Any]],
) -> dict[str, Any]:
    ok = sum(1 for s in scraped if isinstance(s, dict) and s.get("ok"))
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
    return {
        "search_backend": backend,
        "urls_after_blacklist": len(filtered),
        "scrape_ok": ok,
        "scrape_total": len(scraped),
        "render_needed": render_needed,
        "render_used": render_used,
    }

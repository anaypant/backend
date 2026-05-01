"""Internal web-research: search → scrape → LLM coalescence (or legacy LLM-only)."""

from __future__ import annotations

import json
import os
from typing import Any

from clients import llm_internal


def _default_provider() -> str:
    return (os.environ.get("ACS_ENRICHMENT_LLM_PROVIDER") or "openrouter").strip() or "openrouter"


def _default_model() -> str:
    return (os.environ.get("ACS_ENRICHMENT_LLM_MODEL") or "openai/gpt-4o-mini").strip() or "openai/gpt-4o-mini"


def _result_limit_default(result_limit: int | None) -> int:
    if result_limit is not None:
        return max(1, min(20, int(result_limit)))
    raw = (os.environ.get("ACS_WEB_RESEARCH_RESULT_LIMIT") or "5").strip()
    try:
        return max(1, min(20, int(raw)))
    except ValueError:
        return 5


def research_query_to_summary(
    query: str,
    *,
    provider: str | None = None,
    model: str | None = None,
    result_limit: int | None = None,
    seed_urls: list[str] | None = None,
    force_backend: str | None = None,
) -> tuple[dict[str, Any], int]:
    """
    Run a research step for ``query``.

    Modes (``ACS_WEB_RESEARCH_PIPELINE``):

    - ``full`` (default): search API → URL blacklist → concurrent browser-like fetch →
      sanitize → single LLM coalescence. Configure ``ACS_WEB_SEARCH_BACKEND`` (``brave`` / ``tavily`` / ``none``)
      and API keys (``BRAVE_SEARCH_API_KEY`` / ``TAVILY_API_KEY``). Browser tuning uses ``ACS_BROWSER_*`` envs.
    - ``llm_only``: prior behavior (single JSON LLM call without live fetches).

    ``result_limit`` caps how many URLs are scraped after blacklist filtering (default from
    ``ACS_WEB_RESEARCH_RESULT_LIMIT``).

    ``seed_urls`` are scraped directly (company homepage etc.) bypassing the search step.

    ``force_backend`` overrides ``ACS_WEB_SEARCH_BACKEND`` — used by the budget system
    to downgrade to ``duckduckgo`` when the monthly quota is exhausted.

    Returns ``({"summary", "sources", "mode", "tokens_in", "tokens_out", ...}, status)``.
    """
    pipeline = (os.environ.get("ACS_WEB_RESEARCH_PIPELINE") or "full").strip().lower()
    if pipeline != "llm_only":
        from clients.web_research.pipeline import run_research_pipeline

        return run_research_pipeline(
            query,
            result_limit=_result_limit_default(result_limit),
            provider=provider,
            model=model,
            seed_urls=seed_urls,
            force_backend=force_backend,
        )

    q = query.strip() if isinstance(query, str) else ""
    if not q:
        return {"summary": "", "sources": [], "mode": "empty_query", "llm_calls": 0}, 400

    prov = provider or _default_provider()
    mdl = model or _default_model()

    schema_hint = (
        "Return a single JSON object with keys: summary (string), sources (array of objects "
        "with title, url, snippet strings). If you have no verifiable URLs, set url to empty string "
        "and keep snippets factual and short."
    )
    messages = [
        {
            "role": "user",
            "content": f"Research request:\n{q}\n\n{schema_hint}",
        }
    ]
    try:
        body, st = llm_internal.complete(
            model=mdl,
            messages=messages,
            provider=prov,
            response_format="json",
        )
    except Exception as e:
        return {"summary": "", "sources": [], "mode": "error", "error": str(e), "llm_calls": 1}, 503

    if st >= 400:
        return {"summary": "", "sources": [], "mode": "upstream_error", "detail": body, "llm_calls": 1}, st

    raw_text = body.get("text") if isinstance(body.get("text"), str) else ""
    parsed: dict[str, Any] | None = None
    if raw_text.strip():
        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError:
            parsed = None
    if not isinstance(parsed, dict):
        return {"summary": raw_text.strip(), "sources": [], "mode": "llm_non_json", "llm_calls": 1}, 200

    summary = parsed.get("summary") if isinstance(parsed.get("summary"), str) else ""
    sources_raw = parsed.get("sources")
    sources: list[dict[str, str]] = []
    if isinstance(sources_raw, list):
        for item in sources_raw:
            if not isinstance(item, dict):
                continue
            sources.append(
                {
                    "title": str(item.get("title") or "")[:500],
                    "url": str(item.get("url") or "")[:2000],
                    "snippet": str(item.get("snippet") or "")[:4000],
                }
            )

    out = {
        "summary": summary.strip(),
        "sources": sources,
        "mode": "llm_structured",
        "llm_calls": 1,
        "llm": {"provider": prov, "model": mdl, "http_status": st},
    }
    return out, 200

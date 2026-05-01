#!/usr/bin/env python3
"""
Web-search pipeline smoke-test.

Tests each layer of the research pipeline independently, then runs a
full end-to-end query and reports on quality.

Usage (from repo root):
    python backend/scripts/test_web_search.py

Environment variables checked:
    ACS_WEB_SEARCH_BACKEND   brave | tavily | none  (default: none)
    BRAVE_SEARCH_API_KEY     required when backend=brave
    TAVILY_API_KEY           required when backend=tavily
    ACS_WEB_RESEARCH_PIPELINE  full | llm_only      (default: full)
    ACS_ENRICHMENT_LLM_MODEL   model slug           (default: openai/gpt-4o-mini)
    ACS_ENRICHMENT_LLM_PROVIDER  openrouter | openai (default: openrouter)

Exit code 0 = all checks passed.
Exit code 1 = one or more checks failed.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# ── Make repo packages importable ───────────────────────────────────────────
_REPO = Path(__file__).resolve().parent.parent
_RUNNER = _REPO / "core" / "functions" / "runner"
if str(_RUNNER) not in sys.path:
    sys.path.insert(0, str(_RUNNER))

# Load .env if present
_ENV = _REPO / ".env"
if _ENV.exists():
    for line in _ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())


# ── Helpers ──────────────────────────────────────────────────────────────────

PASS = "\033[32m✓\033[0m"
FAIL = "\033[31m✗\033[0m"
WARN = "\033[33m⚠\033[0m"
INFO = "\033[36mℹ\033[0m"

_results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    _results.append((name, ok, detail))
    icon = PASS if ok else FAIL
    msg = f"  {icon}  {name}"
    if detail:
        msg += f"\n       {detail}"
    print(msg)


def section(title: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


# ── Tests ────────────────────────────────────────────────────────────────────

def test_env_config() -> None:
    section("1. Environment / Configuration")
    backend = (os.environ.get("ACS_WEB_SEARCH_BACKEND") or "none").strip().lower()
    pipeline = (os.environ.get("ACS_WEB_RESEARCH_PIPELINE") or "full").strip().lower()
    model = (os.environ.get("ACS_ENRICHMENT_LLM_MODEL") or "openai/gpt-4o-mini").strip()
    provider = (os.environ.get("ACS_ENRICHMENT_LLM_PROVIDER") or "openrouter").strip()

    print(f"  {INFO}  ACS_WEB_SEARCH_BACKEND   = {backend}")
    print(f"  {INFO}  ACS_WEB_RESEARCH_PIPELINE = {pipeline}")
    print(f"  {INFO}  LLM model                = {model} ({provider})")

    if backend == "brave":
        has_key = bool((os.environ.get("BRAVE_SEARCH_API_KEY") or "").strip())
        check("BRAVE_SEARCH_API_KEY set", has_key, "" if has_key else "Set BRAVE_SEARCH_API_KEY to enable Brave search")
    elif backend == "tavily":
        has_key = bool((os.environ.get("TAVILY_API_KEY") or "").strip())
        check("TAVILY_API_KEY set", has_key, "" if has_key else "Set TAVILY_API_KEY to enable Tavily search")
    else:
        check(
            "search backend configured",
            False,
            f"ACS_WEB_SEARCH_BACKEND={backend!r} — no live web search; pipeline will fall back to LLM-only.\n"
            "       Set ACS_WEB_SEARCH_BACKEND=tavily + TAVILY_API_KEY for real results.",
        )

    check("pipeline mode recognised", pipeline in ("full", "llm_only"), f"Unknown pipeline value: {pipeline!r}")


def test_search_layer() -> None:
    section("2. Search Layer")
    from clients.web_research.search import search_top_results

    backend = (os.environ.get("ACS_WEB_SEARCH_BACKEND") or "none").strip().lower()
    if backend == "none":
        print(f"  {WARN}  Skipping live search test (ACS_WEB_SEARCH_BACKEND=none).")
        return

    query = "Elon Musk real estate"
    t0 = time.perf_counter()
    results, used_backend = search_top_results(query, fetch_count=5)
    elapsed = time.perf_counter() - t0

    check("search returns results", len(results) > 0, f"Got {len(results)} results in {elapsed:.1f}s via {used_backend!r}")
    if results:
        first = results[0]
        has_url = bool(first.get("url"))
        check("result has url", has_url, first.get("url", "(none)"))
        print(f"  {INFO}  Top result: {first.get('title', '?')[:60]}")
        print(f"  {INFO}  URL:        {first.get('url', '?')[:80]}")


def test_scrape_layer() -> None:
    section("3. Scrape Layer (single URL)")
    from clients.web_research.browser_fetch import BrowserFetchSession
    from clients.web_research.scrape import scrape_many_concurrent

    test_url = "https://en.wikipedia.org/wiki/Elon_Musk"
    print(f"  {INFO}  Scraping: {test_url}")

    session = BrowserFetchSession()
    t0 = time.perf_counter()
    rows = scrape_many_concurrent(session, [{"url": test_url, "title": "Elon Musk – Wikipedia"}])
    elapsed = time.perf_counter() - t0

    check("scrape completed", len(rows) > 0, f"in {elapsed:.1f}s")
    if rows:
        row = rows[0]
        ok = bool(row.get("ok"))
        text = row.get("text") or ""
        check("scrape ok=True", ok, f"HTTP {row.get('status_code', '?')}")
        check("scraped text non-empty", len(text) > 200, f"{len(text)} chars")
        if text:
            print(f"  {INFO}  First 200 chars: {text[:200].replace(chr(10), ' ')!r}")


def test_llm_layer() -> None:
    section("4. LLM Layer (structured JSON response)")
    from clients import llm_internal

    model = (os.environ.get("ACS_ENRICHMENT_LLM_MODEL") or "openai/gpt-4o-mini").strip()
    provider = (os.environ.get("ACS_ENRICHMENT_LLM_PROVIDER") or "openrouter").strip()

    schema = (
        'Return JSON only: {"summary": "<string>", "sources": [{"title": "<string>", "url": "<string>", "snippet": "<string>"}]}'
    )
    msg = f"Research query: Elon Musk real estate\n\n{schema}"
    t0 = time.perf_counter()
    body, st = llm_internal.complete(
        model=model,
        messages=[{"role": "user", "content": msg}],
        provider=provider,
        response_format="json",
    )
    elapsed = time.perf_counter() - t0

    check("LLM HTTP 200", st < 400, f"status={st} in {elapsed:.1f}s")
    if st < 400:
        raw = body.get("text") or ""
        try:
            parsed = json.loads(raw) if raw.strip() else {}
            summary = parsed.get("summary") or ""
            sources = parsed.get("sources") or []
            check("LLM returns summary", bool(summary), summary[:120] if summary else "(empty)")
            check("LLM returns sources", len(sources) > 0, f"{len(sources)} sources")
            if sources:
                s0 = sources[0]
                print(f"  {INFO}  Source[0]: {s0.get('title', '?')[:60]}")
                print(f"  {INFO}  URL:       {s0.get('url', '?')[:80]}")
        except json.JSONDecodeError as exc:
            check("LLM response is valid JSON", False, str(exc))


def test_full_pipeline() -> None:
    section("5. Full Pipeline (end-to-end)")
    from clients.web_research_internal import research_query_to_summary

    queries = [
        "Elon Musk real estate",
        "Oprah Winfrey property investments",
        "John Smith real estate California",  # common name — tests disambiguation
    ]

    for q in queries:
        print(f"\n  Query: {q!r}")
        t0 = time.perf_counter()
        result, st = research_query_to_summary(q)
        elapsed = time.perf_counter() - t0

        mode = result.get("mode") or "unknown"
        sources = result.get("sources") or []
        summary = result.get("summary") or ""
        pipeline_meta = result.get("pipeline") or {}

        check(
            f"pipeline OK ({q[:30]}…)",
            st < 400,
            f"status={st} mode={mode!r} sources={len(sources)} elapsed={elapsed:.1f}s",
        )
        if st < 400:
            check(f"non-empty summary ({q[:30]}…)", bool(summary), summary[:120] if summary else "(empty)")
            check(f"at least 1 source ({q[:30]}…)", len(sources) > 0, f"Got {len(sources)}")
            if sources:
                s0 = sources[0]
                print(f"    {INFO}  Source[0]: {s0.get('title', '?')[:60]}")
                print(f"    {INFO}  URL:       {s0.get('url', '?')[:80]}")
            if pipeline_meta:
                print(
                    f"    {INFO}  Pipeline: backend={pipeline_meta.get('search_backend')!r}"
                    f" urls_after_blacklist={pipeline_meta.get('urls_after_blacklist')}"
                    f" scrape_ok={pipeline_meta.get('scrape_ok')}"
                )


def test_blacklist() -> None:
    section("6. URL Blacklist")
    from clients.web_research.url_blacklist import filter_results

    sample = [
        {"url": "https://www.linkedin.com/in/elon-musk", "title": "LinkedIn"},
        {"url": "https://en.wikipedia.org/wiki/Elon_Musk", "title": "Wikipedia"},
        {"url": "https://www.facebook.com/elonmusk", "title": "Facebook"},
        {"url": "https://techcrunch.com/elon-musk", "title": "TechCrunch"},
    ]
    filtered = filter_results(sample, limit=10)
    blocked = [r for r in sample if r not in filtered]

    check("linkedin blocked", any("linkedin" in r["url"] for r in blocked), str([r["url"] for r in blocked]))
    check("facebook blocked", any("facebook" in r["url"] for r in blocked))
    check("wikipedia NOT blocked", any("wikipedia" in r["url"] for r in filtered), "Wikipedia should be allowed")
    print(f"  {INFO}  Input={len(sample)} → After blacklist={len(filtered)}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    print("\n╔══════════════════════════════════════════════════╗")
    print("║       ACS Web Search Pipeline – Smoke Test       ║")
    print("╚══════════════════════════════════════════════════╝")

    test_env_config()
    test_blacklist()
    test_search_layer()
    test_scrape_layer()
    test_llm_layer()
    test_full_pipeline()

    passed = sum(1 for _, ok, _ in _results if ok)
    failed = sum(1 for _, ok, _ in _results if not ok)
    total = len(_results)

    print(f"\n{'═' * 60}")
    print(f"  Results: {passed}/{total} passed", end="")
    if failed:
        print(f"  |  {failed} FAILED  ← investigate above")
    else:
        print("  — all good!")
    print(f"{'═' * 60}\n")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

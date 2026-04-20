"""Concurrent page fetch + HTML stripping (worker pool)."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from clients.web_research.browser_fetch import BrowserFetchSession
from clients.web_research.html_to_text import html_to_text
from clients.web_research.render_detect import page_needs_render
from clients.web_research.render_service import fetch_rendered_html, render_service_configured
from clients.web_research.sanitize import sanitize_page_text


def _decode_body(raw: bytes) -> str:
    if not raw:
        return ""
    try:
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return ""


def scrape_one(
    session: BrowserFetchSession,
    item: dict[str, Any],
) -> dict[str, Any]:
    url = item.get("url") if isinstance(item.get("url"), str) else ""
    title = item.get("title") if isinstance(item.get("title"), str) else ""
    if not url.strip():
        return {"url": "", "title": title, "ok": False, "http_status": 400, "text": ""}

    raw, status, final_url, content_type = session.fetch_url(url)
    if status != 200:
        return {
            "url": url,
            "final_url": final_url or url,
            "title": title,
            "ok": False,
            "http_status": status,
            "text": "",
            "render": {"used": False, "needed": False, "reason": None},
        }

    html = _decode_body(raw)
    text = html_to_text(html)
    text = sanitize_page_text(text)

    render_meta: dict[str, Any] = {"used": False, "needed": False, "reason": None, "detect": None}
    needed, detect_reason = page_needs_render(html, text, content_type)
    render_meta["needed"] = needed
    render_meta["detect"] = detect_reason

    if needed and render_service_configured():
        snap, r_st, r_err = fetch_rendered_html(final_url or url)
        if snap and isinstance(snap, str) and snap.strip():
            html2 = snap
            text2 = sanitize_page_text(html_to_text(html2))
            if len(text2.strip()) > len(text.strip()):
                html, text = html2, text2
                render_meta["used"] = True
                render_meta["snapshot_http_status"] = r_st
            else:
                render_meta["used"] = False
                render_meta["reason"] = "render_did_not_improve_text"
                if r_err:
                    render_meta["service_detail"] = r_err[:500]
        else:
            render_meta["used"] = False
            render_meta["reason"] = "render_service_failed"
            render_meta["service_http"] = r_st
            if r_err:
                render_meta["service_detail"] = str(r_err)[:500]
    elif needed and not render_service_configured():
        render_meta["reason"] = "render_needed_but_service_not_configured"

    return {
        "url": url,
        "final_url": final_url or url,
        "title": title,
        "ok": True,
        "http_status": status,
        "text": text,
        "render": render_meta,
    }


def scrape_many_concurrent(
    session: BrowserFetchSession,
    items: list[dict[str, Any]],
    *,
    max_workers: int | None = None,
) -> list[dict[str, Any]]:
    if not items:
        return []
    workers = max_workers
    if workers is None:
        workers = max(1, min(8, int((os.environ.get("ACS_WEB_SCRAPE_MAX_WORKERS") or "5").strip() or 5)))
    workers = max(1, min(12, workers))

    results: list[dict[str, Any]] = [dict() for _ in items]

    def _job(idx: int, it: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        return idx, scrape_one(session, it)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(_job, i, it) for i, it in enumerate(items)]
        for fut in as_completed(futs):
            idx, row = fut.result()
            results[idx] = row
    return results

"""Heuristics for whether a URL likely needs a JS-capable renderer (vs static HTML)."""

from __future__ import annotations

import os
import re

# Empty or nearly-empty mount points common in SPAs
_SPA_ROOT_PATTERNS = (
    re.compile(r"""<div[^>]+id\s*=\s*["']root["'][^>]*>\s*</div>""", re.I),
    re.compile(r"""<div[^>]+id\s*=\s*["']app["'][^>]*>\s*</div>""", re.I),
    re.compile(r"""<div[^>]+id\s*=\s*["']__next["'][^>]*>\s*</div>""", re.I),
)

# High-signal client-app markers (avoid ``noscript`` / ``__NEXT_DATA__`` alone — too common on healthy pages).
_SECONDARY_SPA_MARKERS = (
    "webpackchunk",
    "data-reactroot",
    "window.__nuxt__",
    "window.__initial_state__",
    "static/js/main.",
    "/_next/static/",
)

_FRAMEWORK_SCRIPT = re.compile(
    r"""<script[^>]+src\s*=\s*["'][^"']*(?:react|vue|angular|svelte|next/static|nuxt|vite)[^"']*["']""",
    re.I,
)


def _env_int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def page_needs_render(
    html: str,
    plain_text: str,
    content_type: str,
) -> tuple[bool, str]:
    """
    Return ``(needs_render, reason_code)``.

    Conservative: prefers false positives on "needs render" only when thin content **and**
    SPA / client-bundle signals exist, so we do not call a render service for every blog page.

    ``reason_code`` is machine-readable for audit logs (``ok``, ``non_html``, ``thin_spa_shell``, ...).
    """
    if (os.environ.get("ACS_RENDER_DETECT") or "on").strip().lower() in ("0", "false", "off"):
        return False, "detect_disabled"

    ct = (content_type or "").split(";")[0].strip().lower()
    if ct and ct not in ("text/html", "application/xhtml+xml", ""):
        if "json" in ct:
            return False, "non_html_json"
        if "javascript" in ct or ct == "application/javascript":
            return False, "non_html_js"
        # XML feeds, PDFs, etc.
        if "html" not in ct:
            return False, f"non_html_{ct[:40]}"

    h = html if isinstance(html, str) else ""
    t = plain_text if isinstance(plain_text, str) else ""
    t_len = len(t.strip())
    h_lower = h[:500_000].lower()

    min_chars = max(20, _env_int("ACS_RENDER_MIN_TEXT_CHARS", 120))
    min_ratio = float((os.environ.get("ACS_RENDER_MIN_TEXT_TO_HTML_RATIO") or "0.012").strip() or 0.012)
    if min_ratio < 0.0001:
        min_ratio = 0.012

    html_len = max(len(h), 1)
    ratio = t_len / html_len

    # Strong: explicit noscript / enable-js messaging with little extractable text
    if t_len < min_chars:
        for phrase in ("enable javascript", "javascript is required", "please enable javascript"):
            if phrase in h_lower:
                return True, "thin_enable_js_message"

        for rx in _SPA_ROOT_PATTERNS:
            if rx.search(h):
                return True, "thin_spa_empty_mount"

        if _FRAMEWORK_SCRIPT.search(h) and ratio < min_ratio * 3:
            return True, "thin_client_bundle"

        hits = sum(1 for m in _SECONDARY_SPA_MARKERS if m in h_lower)
        if hits >= 2 and t_len < min_chars * 2:
            return True, "thin_spa_signals"

        if t_len < max(30, min_chars // 4) and ("<script" in h_lower) and ratio < min_ratio:
            return True, "thin_scripts_low_signal"

    return False, "ok"

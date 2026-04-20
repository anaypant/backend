"""Minimal HTML → plain text (stdlib only)."""

from __future__ import annotations

import re
from html.parser import HTMLParser


class _HTMLStripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        if t in ("script", "style", "noscript", "template"):
            self._skip = True

    def handle_endtag(self, tag):
        t = tag.lower()
        if t in ("script", "style", "noscript", "template"):
            self._skip = False
        if t in ("p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "section", "article"):
            self._chunks.append("\n")

    def handle_data(self, data):
        if not self._skip and data:
            self._chunks.append(data)

    def text(self) -> str:
        raw = "".join(self._chunks)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def html_to_text(html: str) -> str:
    if not isinstance(html, str) or not html.strip():
        return ""
    p = _HTMLStripper()
    try:
        p.feed(html)
        p.close()
    except Exception:
        return re.sub(r"<[^>]+>", " ", html)[:200_000]
    return p.text()

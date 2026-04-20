import unittest

from clients.web_research.render_detect import page_needs_render
from clients.web_research.sanitize import sanitize_page_text, strip_non_ascii
from clients.web_research.url_blacklist import filter_results, is_blocked_url


class RenderDetectTest(unittest.TestCase):
    def test_detects_empty_spa_mount(self):
        html = '<!doctype html><html><body><div id="root"></div><script src="/bundle.js"></script></body></html>'
        needed, reason = page_needs_render(html, " ", "text/html; charset=utf-8")
        self.assertTrue(needed)
        self.assertEqual(reason, "thin_spa_empty_mount")

    def test_skips_substantial_article(self):
        html = "<html><body><article><p>" + ("word " * 200) + "</p></article></body></html>"
        text = "word " * 200
        needed, reason = page_needs_render(html, text, "text/html")
        self.assertFalse(needed)
        self.assertEqual(reason, "ok")


class WebResearchUtilitiesTest(unittest.TestCase):
    def test_strip_non_ascii(self):
        self.assertEqual(strip_non_ascii("caf résumé"), "caf rsum")

    def test_sanitize_page_text(self):
        self.assertIn("hello", sanitize_page_text("hello \x00 \n\t world"))

    def test_blocked_social_hosts(self):
        self.assertTrue(is_blocked_url("https://www.facebook.com/foo"))
        self.assertTrue(is_blocked_url("https://bit.ly/abc"))

    def test_filter_results_respects_limit(self):
        rows = [
            {"url": "https://example.com/a", "title": "a"},
            {"url": "https://facebook.com/x", "title": "x"},
            {"url": "https://example.com/b", "title": "b"},
        ]
        out = filter_results(rows, limit=2)
        self.assertEqual(len(out), 2)
        self.assertTrue(all("example.com" in r["url"] for r in out))


if __name__ == "__main__":
    unittest.main()

"""Tests for ``web_research_internal.research_query_to_summary`` and the full scrape pipeline (mocked)."""

from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from clients import web_research_internal
from clients.web_research.pipeline import run_research_pipeline
from clients.web_research.search import search_top_results


class SearchTopResultsTest(unittest.TestCase):
    @patch.dict(os.environ, {"ACS_WEB_SEARCH_BACKEND": "none"}, clear=False)
    def test_none_backend_returns_empty_without_network(self):
        rows, backend = search_top_results("any query", fetch_count=5)
        self.assertEqual(backend, "none")
        self.assertEqual(rows, [])


class WebResearchLlmOnlyTest(unittest.TestCase):
    @patch.dict(os.environ, {"ACS_WEB_RESEARCH_PIPELINE": "llm_only"}, clear=False)
    @patch("clients.web_research_internal.llm_internal.complete")
    def test_llm_only_returns_structured_summary_and_sources(self, mock_llm):
        mock_llm.return_value = (
            {
                "text": json.dumps(
                    {
                        "summary": "Regional inventory is tight.",
                        "sources": [
                            {"title": "Local market", "url": "https://example.com/r", "snippet": "Data point."},
                        ],
                    }
                ),
            },
            200,
        )
        res, st = web_research_internal.research_query_to_summary("  housing trends  ")
        self.assertEqual(st, 200)
        self.assertEqual(res["summary"], "Regional inventory is tight.")
        self.assertEqual(res["mode"], "llm_structured")
        self.assertEqual(len(res["sources"]), 1)
        self.assertEqual(res["sources"][0]["url"], "https://example.com/r")
        mock_llm.assert_called_once()

    @patch.dict(os.environ, {"ACS_WEB_RESEARCH_PIPELINE": "llm_only"}, clear=False)
    def test_empty_query_returns_400(self):
        res, st = web_research_internal.research_query_to_summary("  \n\t  ")
        self.assertEqual(st, 400)
        self.assertEqual(res["mode"], "empty_query")

    @patch.dict(os.environ, {"ACS_WEB_RESEARCH_PIPELINE": "llm_only"}, clear=False)
    @patch("clients.web_research_internal.llm_internal.complete")
    def test_llm_upstream_error(self, mock_llm):
        mock_llm.return_value = ({"error": "rate limited"}, 502)
        res, st = web_research_internal.research_query_to_summary("anything")
        self.assertEqual(st, 502)
        self.assertEqual(res["mode"], "upstream_error")

    @patch.dict(os.environ, {"ACS_WEB_RESEARCH_PIPELINE": "llm_only"}, clear=False)
    @patch("clients.web_research_internal.llm_internal.complete", side_effect=RuntimeError("gateway down"))
    def test_llm_exception_returns_503(self, _mock_llm):
        res, st = web_research_internal.research_query_to_summary("q")
        self.assertEqual(st, 503)
        self.assertEqual(res["mode"], "error")
        self.assertIn("gateway", res.get("error", ""))

    @patch.dict(os.environ, {"ACS_WEB_RESEARCH_PIPELINE": "llm_only"}, clear=False)
    @patch("clients.web_research_internal.llm_internal.complete")
    def test_non_json_llm_text_uses_plain_summary(self, mock_llm):
        mock_llm.return_value = ({"text": "Just a prose answer without JSON."}, 200)
        res, st = web_research_internal.research_query_to_summary("q")
        self.assertEqual(st, 200)
        self.assertEqual(res["mode"], "llm_non_json")
        self.assertIn("prose", res["summary"].lower())
        self.assertEqual(res["sources"], [])


class WebResearchFullPipelineTest(unittest.TestCase):
    @patch.dict(os.environ, {"ACS_WEB_RESEARCH_PIPELINE": "full"}, clear=False)
    @patch("clients.web_research.pipeline.llm_internal.complete")
    @patch("clients.web_research.pipeline.scrape_many_concurrent")
    @patch("clients.web_research.pipeline.search_top_results")
    def test_run_research_pipeline_search_scrape_coalesce_llm(
        self,
        mock_search,
        mock_scrape,
        mock_llm,
    ):
        mock_search.return_value = (
            [{"url": "https://example.org/page", "title": "Page", "snippet": "lead-in"}],
            "stub_backend",
        )
        mock_scrape.return_value = [
            {
                "ok": True,
                "title": "Page",
                "final_url": "https://example.org/page",
                "text": ("Substantive body paragraph. " * 30),
            },
        ]
        mock_llm.return_value = (
            {
                "text": json.dumps(
                    {
                        "summary": "Synthesized from scrape.",
                        "sources": [
                            {
                                "title": "Page",
                                "url": "https://example.org/page",
                                "snippet": "Evidence line.",
                            },
                        ],
                    }
                ),
            },
            200,
        )

        out, st = run_research_pipeline("market overview", result_limit=2)
        self.assertEqual(st, 200)
        self.assertEqual(out["mode"], "scrape_then_llm")
        self.assertEqual(out["summary"], "Synthesized from scrape.")
        self.assertEqual(len(out["sources"]), 1)
        self.assertIn("pipeline", out)
        self.assertEqual(out["pipeline"].get("search_backend"), "stub_backend")
        mock_search.assert_called_once()
        mock_scrape.assert_called_once()
        mock_llm.assert_called_once()

    @patch.dict(os.environ, {"ACS_WEB_RESEARCH_PIPELINE": "full"}, clear=False)
    @patch("clients.web_research.pipeline.llm_internal.complete")
    @patch("clients.web_research.pipeline.scrape_many_concurrent")
    @patch("clients.web_research.pipeline.search_top_results")
    def test_research_query_to_summary_full_entrypoint(
        self,
        mock_search,
        mock_scrape,
        mock_llm,
    ):
        """``research_query_to_summary`` lazy-imports the pipeline when not ``llm_only``."""
        mock_search.return_value = ([], "none")
        mock_scrape.return_value = []
        mock_llm.return_value = (
            {"text": json.dumps({"summary": "No hits path", "sources": []})},
            200,
        )
        res, st = web_research_internal.research_query_to_summary("orphan query")
        self.assertEqual(st, 200)
        self.assertEqual(res["summary"], "No hits path")
        self.assertEqual(res["mode"], "scrape_then_llm")


if __name__ == "__main__":
    unittest.main()

import os
import unittest
from unittest.mock import patch

from workflows import registry as wf_registry


class DemoJokeWorkflowTest(unittest.TestCase):
    @patch("workflows.demo_joke_to_profile.llm_internal.complete")
    @patch("tools.db_profile.db_internal.upsert_merge")
    def test_demo_happy_path(self, mock_upsert, mock_llm):
        mock_llm.return_value = ({"text": "Why did the agent cross the road? Listings."}, 200)
        mock_upsert.return_value = ({}, 200)
        os.environ["ACS_DEMO_LLM_MODEL"] = "test/model"
        os.environ.pop("ACS_DEMO_LLM_PROVIDER", None)

        acs = {
            "state_version": 1,
            "correlation_id": "c1",
            "source": {"provider": "test", "event_type": "x"},
            "payload": {},
            "user_id": "realtor-uid-1",
        }
        out = wf_registry.run_workflow("demo.joke_to_profile_v1", acs)
        meta = out.get("metadata") or {}
        core = meta.get("core") if isinstance(meta.get("core"), dict) else {}
        self.assertEqual(core.get("status"), "completed")
        mock_llm.assert_called_once()
        self.assertEqual(mock_llm.call_args.kwargs.get("provider"), "openrouter")
        mock_upsert.assert_called_once()
        args, kwargs = mock_upsert.call_args
        self.assertIn("workflowDemo", args[1])

    @patch("workflows.demo_joke_to_profile.llm_internal.complete")
    def test_demo_fails_without_user(self, mock_llm):
        mock_llm.return_value = ({"text": "x"}, 200)
        acs = {
            "state_version": 1,
            "correlation_id": "c1",
            "source": {"provider": "test", "event_type": "x"},
            "payload": {},
        }
        out = wf_registry.run_workflow("demo.joke_to_profile_v1", acs)
        meta = out.get("metadata") or {}
        core = meta.get("core") if isinstance(meta.get("core"), dict) else {}
        self.assertEqual(core.get("status"), "failed")
        mock_llm.assert_not_called()


if __name__ == "__main__":
    unittest.main()

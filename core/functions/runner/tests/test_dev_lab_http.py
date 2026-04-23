import os
import unittest
from unittest.mock import patch

from dev_lab_http import dev_lab_enabled, try_dev_lab_response


class DevLabHttpTest(unittest.TestCase):
    def test_non_dev_body_returns_none(self):
        self.assertIsNone(try_dev_lab_response({"workflow_id": "contact.enrichment_v1", "state": {}}))

    def test_marker_without_env_returns_501(self):
        os.environ.pop("ACS_ENABLE_DEV_LAB", None)
        out = try_dev_lab_response({"__ACS_DEV_LAB__": "catalog"})
        self.assertIsNotNone(out)
        payload, st = out
        self.assertEqual(st, 501)
        self.assertEqual(payload.get("error"), "dev_lab_disabled")

    def test_catalog_when_enabled(self):
        os.environ["ACS_ENABLE_DEV_LAB"] = "1"
        try:
            self.assertTrue(dev_lab_enabled())
            out = try_dev_lab_response({"__ACS_DEV_LAB__": "catalog"})
            self.assertIsNotNone(out)
            payload, st = out
            self.assertEqual(st, 200)
            ids = [w["id"] for w in payload["workflows"]]
            self.assertIn("contact.enrichment_v1", ids)
            tool_ids = [t["id"] for t in payload["tools"]]
            self.assertIn("db.merge_realtor_profile", tool_ids)
        finally:
            os.environ.pop("ACS_ENABLE_DEV_LAB", None)

    def test_run_unit_checks_when_enabled(self):
        os.environ["ACS_ENABLE_DEV_LAB"] = "1"
        try:
            out = try_dev_lab_response({"__ACS_DEV_LAB__": "run_unit_checks", "acting_uid": "uid-test"})
            self.assertIsNotNone(out)
            payload, st = out
            self.assertEqual(st, 200)
            self.assertIn("summary", payload)
            self.assertTrue(payload.get("ok"), payload)
        finally:
            os.environ.pop("ACS_ENABLE_DEV_LAB", None)

    def test_run_unit_checks_requires_acting_uid(self):
        os.environ["ACS_ENABLE_DEV_LAB"] = "1"
        try:
            out = try_dev_lab_response({"__ACS_DEV_LAB__": "run_unit_checks"})
            self.assertIsNotNone(out)
            payload, st = out
            self.assertEqual(st, 400)
            self.assertEqual(payload.get("error"), "acting_uid string required")
        finally:
            os.environ.pop("ACS_ENABLE_DEV_LAB", None)

    @patch("dev_lab_http.tool_registry.run_tool")
    def test_run_tool_delegates(self, mock_run):
        os.environ["ACS_ENABLE_DEV_LAB"] = "1"
        mock_run.return_value = ({"ok": True}, 200)
        try:
            out = try_dev_lab_response(
                {
                    "__ACS_DEV_LAB__": "run_tool",
                    "tool_id": "db.merge_realtor_profile",
                    "args": {"data": {"x": 1}},
                    "acting_uid": "u1",
                    "acs": {"metadata": {"execution_policy": {"volatile_external_allowed": False}}},
                }
            )
            self.assertIsNotNone(out)
            payload, st = out
            self.assertEqual(st, 200)
            self.assertEqual(payload.get("http_status"), 200)
            mock_run.assert_called_once()
        finally:
            os.environ.pop("ACS_ENABLE_DEV_LAB", None)


if __name__ == "__main__":
    unittest.main()

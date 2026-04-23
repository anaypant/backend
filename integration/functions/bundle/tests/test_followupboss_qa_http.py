import json
import unittest
from unittest.mock import patch

from providers.followupboss.qa_http import qa_unit_checks


class DummyReq:
    method = "POST"


class FollowupbossQaHttpTest(unittest.TestCase):
    @patch("providers.followupboss.qa_http.resolve_realtor_bearer", return_value=({"uid": "u1"}, None, "t"))
    def test_qa_unit_checks_ok(self, _mock_auth):
        raw, status, _ = qa_unit_checks(DummyReq())
        self.assertEqual(status, 200)
        body = json.loads(raw)
        self.assertTrue(body.get("ok"), body)
        self.assertGreater(body.get("summary", {}).get("passed", 0), 0)


if __name__ == "__main__":
    unittest.main()

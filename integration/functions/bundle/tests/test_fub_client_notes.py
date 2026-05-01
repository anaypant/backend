"""Tests for FUB notes API helpers on FubClient."""

import unittest
from unittest.mock import patch

from providers.followupboss.client import FubClient


class FubClientNotesTest(unittest.TestCase):
    @patch("providers.followupboss.client.get_json")
    def test_list_notes_builds_query(self, mock_get):
        mock_get.return_value = ({"notes": [{"id": 1}]}, 200)
        client = FubClient(access_token_plain="tok")
        body, st = client.list_notes(99, limit=50, offset=10)
        self.assertEqual(st, 200)
        self.assertEqual(body.get("notes"), [{"id": 1}])
        mock_get.assert_called_once()
        url = mock_get.call_args[0][0]
        self.assertIn("https://api.followupboss.com/v1/notes?", url)
        self.assertIn("personId=99", url)
        self.assertIn("limit=50", url)
        self.assertIn("offset=10", url)


if __name__ == "__main__":
    unittest.main()

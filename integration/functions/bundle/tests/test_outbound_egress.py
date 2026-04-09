import unittest
from unittest.mock import patch

from providers.followupboss import egress


class OutboundEgressTest(unittest.TestCase):
    @patch("providers.followupboss.egress._client_for_connection")
    def test_create_note_action(self, client_factory):
        client = client_factory.return_value
        client.create_note.return_value = ({"id": 1}, 200)

        out = egress.apply_outbound_actions(
            "u1",
            [{"name": "createNote", "payload": {"personId": 1, "body": "hello"}}],
        )
        self.assertTrue(out["ok"])
        self.assertEqual(len(out["results"]), 1)


if __name__ == "__main__":
    unittest.main()

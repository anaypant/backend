import json
import unittest
from unittest.mock import patch

from providers.followupboss import oauth


class DummyReq:
    def __init__(self, headers=None):
        self.headers = headers or {"X-Forwarded-Host": "api.example.dev"}


class DisconnectIdempotentTest(unittest.TestCase):
    @patch("providers.followupboss.oauth.save_fub_profile")
    @patch(
        "providers.followupboss.oauth.load_realtor_profile",
        return_value=(
            {
                "integrations": {
                    "followupboss": {
                        "connection": {"status": "disconnected"},
                        "webhooks": {},
                    }
                }
            },
            200,
        ),
    )
    @patch(
        "providers.followupboss.oauth.resolve_realtor_bearer",
        return_value=({"uid": "u1", "role": "realtor"}, None, None),
    )
    def test_disconnect_noop_when_already_disconnected(self, _resolve, _load, mock_save):
        body, status, _ = oauth.disconnect(DummyReq())
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body).get("idempotent"))
        mock_save.assert_not_called()


if __name__ == "__main__":
    unittest.main()

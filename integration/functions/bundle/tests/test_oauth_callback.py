import json
import unittest
from unittest.mock import patch

from providers.followupboss import oauth


class DummyReq:
    def __init__(self, args=None, headers=None):
        self.args = args or {}
        self.headers = headers or {"X-Forwarded-Host": "api.example.dev"}


class OauthCallbackSyncTest(unittest.TestCase):
    @patch("providers.followupboss.oauth.save_fub_profile_by_connection_id")
    @patch("providers.followupboss.oauth._ensure_all_webhooks", return_value=({"ok": True, "created": 53}, 200))
    @patch("providers.followupboss.oauth.put_secret", side_effect=["sm://a", "sm://r"])
    @patch("providers.followupboss.oauth.FubClient.exchange_code", return_value=({"access_token": "a", "refresh_token": "r", "expires_in": 3600}, 200))
    @patch("providers.followupboss.oauth.load_fub_profile_by_connection_id", return_value=({}, {"auth": {"oauthPending": {"state": "u1.n1", "nonce": "n1", "expiresAtEpoch": 9999999999}}}))
    @patch("providers.followupboss.oauth._state_parse", return_value=("u1", "n1", True))
    def test_callback_triggers_webhook_sync(self, *_mocks):
        req = DummyReq(args={"state": "u1.n1", "code": "abc"})
        body, status, _ = oauth.oauth_callback(req)
        self.assertEqual(status, 200)
        self.assertIn("webhooks", body)


class OauthCallbackIdempotentTest(unittest.TestCase):
    @patch("providers.followupboss.oauth.save_fub_profile_by_connection_id")
    @patch(
        "providers.followupboss.oauth.load_fub_profile_by_connection_id",
        return_value=(
            {},
            {
                "auth": {
                    "accessTokenRef": "acs-sec://v1/x",
                    "oauthPending": {},
                },
                "connection": {"status": "connected"},
                "webhooks": {"registered": True},
            },
        ),
    )
    @patch("providers.followupboss.oauth._state_parse", return_value=("u1", "n1", True))
    def test_callback_idempotent_when_already_connected(self, *_mocks):
        req = DummyReq(args={"state": "u1.n1", "code": "would_fail_if_exchanged"})
        body, status, _ = oauth.oauth_callback(req)
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertTrue(payload.get("idempotent"))
        self.assertEqual(payload.get("webhooks"), {"registered": True})


if __name__ == "__main__":
    unittest.main()

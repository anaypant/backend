import json
import os
import unittest
from unittest.mock import patch

from providers.followupboss import oauth


class DummyReq:
    def __init__(self, args=None, headers=None, method="GET"):
        self.args = args or {}
        self.headers = headers or {"X-Forwarded-Host": "api.example.dev"}
        self.method = method

    def get_json(self, silent=True):
        return {}


class OauthCallbackDeferredTest(unittest.TestCase):
    @patch.dict(
        os.environ,
        {"FUB_WEBHOOK_SYNC_QUEUE": "projects/p/locations/l/queues/q", "FUB_WEBHOOK_SYNC_WORKER_URL": "https://bridge.example.run.app"},
        clear=False,
    )
    @patch("store.domain_events._try_publish")
    @patch("providers.followupboss.oauth.enqueue_fub_webhook_sync", return_value=(True, None))
    @patch("providers.followupboss.oauth.save_fub_profile_by_connection_id")
    @patch("providers.followupboss.oauth.put_secret", side_effect=["sm://a", "sm://r"])
    @patch(
        "providers.followupboss.oauth.FubClient.exchange_code",
        return_value=({"access_token": "a", "refresh_token": "r", "expires_in": 3600}, 200),
    )
    @patch(
        "providers.followupboss.oauth.load_fub_profile_by_connection_id",
        return_value=({}, {"auth": {"oauthPending": {"state": "u1.n1", "nonce": "n1", "expiresAtEpoch": 9999999999}}}),
    )
    @patch("providers.followupboss.oauth._state_parse", return_value=("u1", "n1", True))
    def test_callback_defers_webhook_sync(self, *_mocks):
        req = DummyReq(args={"state": "u1.n1", "code": "abc"})
        body, status, _ = oauth.oauth_callback(req)
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertTrue(payload.get("webhookSyncDeferred"))
        self.assertEqual(payload.get("webhooks", {}).get("syncStatus"), "pending")


class InternalWebhookSyncTest(unittest.TestCase):
    def test_rejects_without_auth(self):
        req = DummyReq(method="POST", headers={})
        body, status, _ = oauth.internal_webhook_sync(req)
        self.assertEqual(status, 401)


class ResyncWebhooksDeferredTest(unittest.TestCase):
    @patch.dict(
        os.environ,
        {"FUB_WEBHOOK_SYNC_QUEUE": "projects/p/locations/l/queues/q", "FUB_WEBHOOK_SYNC_WORKER_URL": "https://bridge.example.run.app"},
        clear=False,
    )
    @patch("providers.followupboss.oauth.emit_followupboss_webhooks_resynced")
    @patch("providers.followupboss.oauth.save_fub_profile", return_value=({"ok": True}, 200))
    @patch("providers.followupboss.oauth.enqueue_fub_webhook_sync", return_value=(True, None))
    @patch(
        "providers.followupboss.oauth.load_realtor_profile",
        return_value=(
            {
                "integrations": {
                    "followupboss": {
                        "auth": {"accessTokenRef": "sm://access"},
                        "connection": {"status": "connected"},
                    }
                }
            },
            200,
        ),
    )
    @patch("providers.followupboss.oauth.resolve_realtor_bearer", return_value=({"uid": "u1"}, None, None))
    def test_resync_enqueues_when_queue_configured(self, *_mocks):
        req = DummyReq(method="POST")
        body, status, _ = oauth.resync_webhooks(req)
        self.assertEqual(status, 202)
        payload = json.loads(body)
        self.assertTrue(payload.get("deferred"))
        self.assertEqual(payload.get("webhooks", {}).get("syncStatus"), "pending")


if __name__ == "__main__":
    unittest.main()

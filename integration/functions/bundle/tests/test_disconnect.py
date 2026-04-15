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

    @patch("providers.followupboss.oauth.delete_followupboss_event_ledger_for_uid", return_value=(2, None))
    @patch(
        "providers.followupboss.oauth._disconnect_unregister_webhooks",
        return_value={
            "callbackUrl": "https://api.example.dev/integrations/webhooks/followupboss?connectionId=u1",
            "removed": 3,
            "listHttpStatus": 200,
            "usedRefresh": True,
            "usedApiKeyFallback": False,
            "error": None,
        },
    )
    @patch("providers.followupboss.oauth.save_fub_profile")
    @patch(
        "providers.followupboss.oauth.load_realtor_profile",
        return_value=(
            {
                "integrations": {
                    "followupboss": {
                        "connection": {"status": "connected"},
                        "webhooks": {"ok": False},
                        "auth": {"accessTokenRef": "acs-sec://x", "refreshTokenRef": "acs-sec://y"},
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
    def test_disconnect_runs_fub_and_ledger_cleanup(self, _resolve, _load, mock_save, _wh, _ledger):
        mock_save.return_value = ({"path": "Realtors/u1", "merge": True}, 200)
        body, status, _ = oauth.disconnect(DummyReq())
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data.get("eventLedgerDeleted"), 2)
        self.assertEqual(data.get("webhookCleanup", {}).get("removed"), 3)
        self.assertTrue(data.get("webhookCleanup", {}).get("usedRefresh"))
        mock_save.assert_called_once()


if __name__ == "__main__":
    unittest.main()

import json
import unittest
from unittest.mock import patch

from providers.followupboss import oauth
from store import common


class DummyReq:
    def __init__(self, path: str, method: str = "GET", headers=None, args=None):
        self.path = path
        self.method = method
        self.headers = headers or {}
        self.args = args or {}


class OauthStartTest(unittest.TestCase):
    @patch(
        "providers.followupboss.oauth.resolve_realtor_bearer",
        return_value=({"uid": "u1", "role": "realtor"}, None, None),
    )
    @patch("providers.followupboss.oauth.save_fub_profile", return_value=({"ok": True}, 200))
    @patch("providers.followupboss.oauth.load_realtor_profile", return_value=({}, 404))
    @patch("providers.followupboss.oauth._resolve_authorize_url", return_value=("https://auth.example", None))
    def test_oauth_start_returns_authorize_url(self, *_mocks):
        req = DummyReq("/integrations/followupboss/oauth/start", headers={"X-Forwarded-Host": "api.example.dev"})
        body, status, _ = oauth.oauth_start(req)
        self.assertEqual(status, 200)
        self.assertIn("authorizeUrl", body)

    @patch(
        "providers.followupboss.oauth.resolve_realtor_bearer",
        return_value=({"uid": "u1", "role": "realtor"}, None, None),
    )
    @patch("providers.followupboss.oauth.save_fub_profile", return_value=({"ok": True}, 200))
    @patch("providers.followupboss.oauth.now_epoch", return_value=1_000_000)
    @patch(
        "providers.followupboss.oauth.load_realtor_profile",
        return_value=(
            {
                "integrations": {
                    "followupboss": {
                        "auth": {
                            "oauthPending": {
                                "state": "u1.reuseNonce",
                                "nonce": "reuseNonce",
                                "createdAtEpoch": 1,
                                "expiresAtEpoch": 9_999_999_999,
                            }
                        },
                    }
                }
            },
            200,
        ),
    )
    @patch("providers.followupboss.oauth._state_parse", return_value=("u1", "reuseNonce", True))
    @patch("providers.followupboss.oauth._resolve_authorize_url", return_value=("https://auth.example", None))
    def test_oauth_start_reuses_non_expired_pending(self, *_mocks):
        req = DummyReq("/integrations/followupboss/oauth/start", headers={"X-Forwarded-Host": "api.example.dev"})
        body, status, _ = oauth.oauth_start(req)
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(payload.get("state"), "u1.reuseNonce")
        self.assertTrue(payload.get("idempotent"))

    @patch(
        "providers.followupboss.oauth.resolve_realtor_bearer",
        return_value=({"uid": "u1", "role": "realtor"}, None, None),
    )
    @patch(
        "providers.followupboss.oauth.load_realtor_profile",
        return_value=(
            {
                "integrations": {
                    "followupboss": {
                        "connection": {"status": "connected", "provider": "followupboss"},
                        "auth": {"accessTokenRef": "acs-sec://x"},
                    }
                }
            },
            200,
        ),
    )
    def test_oauth_start_conflict_when_already_connected(self, *_mocks):
        req = DummyReq("/integrations/followupboss/oauth/start", headers={"X-Forwarded-Host": "api.example.dev"})
        body, status, _ = oauth.oauth_start(req)
        self.assertEqual(status, 409)
        payload = json.loads(body)
        self.assertEqual(payload.get("error"), "already_connected")
        self.assertEqual(payload.get("phase"), "fub_oauth")

    def test_integration_auth_error_includes_phase_and_hint(self):
        body, status, _ = common.integration_auth_error_response("missing bearer token")
        self.assertEqual(status, 401)
        p = json.loads(body)
        self.assertEqual(p.get("phase"), "integration_auth")
        self.assertIn("hint", p)


if __name__ == "__main__":
    unittest.main()

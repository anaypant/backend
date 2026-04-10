import unittest
from unittest.mock import patch

from providers.followupboss import oauth


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


if __name__ == "__main__":
    unittest.main()

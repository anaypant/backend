import base64
import os
import unittest
from unittest.mock import patch

from providers.followupboss.client import FubClient


class FubClientOauthTest(unittest.TestCase):
    def setUp(self):
        self.env = {
            "FUB_OAUTH_TOKEN_URL": "https://app.followupboss.com/oauth/token",
            "FUB_OAUTH_CLIENT_ID": "client_id_value",
            "FUB_OAUTH_CLIENT_SECRET": "client_secret_value",
        }

    @patch("providers.followupboss.client.post_form", return_value=({"access_token": "a"}, 200))
    def test_exchange_code_uses_basic_auth_not_body_secrets(self, mock_post):
        with patch.dict(os.environ, self.env, clear=False):
            body, status = FubClient().exchange_code("thecode", "https://example/cb", "uid.nonce.sig")
        self.assertEqual(status, 200)
        self.assertEqual(body.get("access_token"), "a")
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        url, form = args[0], args[1]
        self.assertIn("followupboss", url)
        self.assertEqual(
            form,
            {
                "grant_type": "authorization_code",
                "code": "thecode",
                "redirect_uri": "https://example/cb",
                "state": "uid.nonce.sig",
            },
        )
        headers = kwargs.get("headers") or {}
        expected_basic = base64.b64encode(b"client_id_value:client_secret_value").decode("ascii")
        self.assertEqual(headers.get("Authorization"), f"Basic {expected_basic}")
        self.assertNotIn("client_id", form)
        self.assertNotIn("client_secret", form)

    def test_exchange_code_rejects_empty_state(self):
        with patch.dict(os.environ, self.env, clear=False):
            body, status = FubClient().exchange_code("c", "https://cb", "")
        self.assertEqual(status, 400)
        self.assertIn("missing_state", body.get("error", ""))

    @patch("providers.followupboss.client.post_form", return_value=({"access_token": "n"}, 200))
    def test_refresh_token_uses_basic_auth(self, mock_post):
        with patch.dict(os.environ, self.env, clear=False):
            body, status = FubClient().refresh_token("rtok")
        self.assertEqual(status, 200)
        mock_post.assert_called_once()
        _url, form = mock_post.call_args[0]
        headers = mock_post.call_args[1].get("headers") or {}
        self.assertEqual(
            form,
            {"grant_type": "refresh_token", "refresh_token": "rtok"},
        )
        expected_basic = base64.b64encode(b"client_id_value:client_secret_value").decode("ascii")
        self.assertEqual(headers.get("Authorization"), f"Basic {expected_basic}")


if __name__ == "__main__":
    unittest.main()

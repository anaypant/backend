import json
import os
import unittest
from unittest.mock import MagicMock, patch

from handlers import publish as publish_mod


class _Req:
    def __init__(self, json_body=None, headers=None):
        self._json = json_body
        self.headers = headers or {}

    def get_json(self, silent=True):
        return self._json


class PublishHandlerTest(unittest.TestCase):
    @patch.dict(os.environ, {"PUBSUB_TOPIC_ID": "projects/p/topics/t"}, clear=False)
    @patch("handlers.publish.pubsub_v1.PublisherClient")
    @patch("handlers.publish.verify_platform_request", return_value=({"email": "x@.iam.gserviceaccount.com"}, None))
    def test_publish_ok(self, _verify, mock_pc_cls):
        mock_future = MagicMock()
        mock_future.result.return_value = "msg-1"
        mock_pub = MagicMock()
        mock_pub.publish.return_value = mock_future
        mock_pc_cls.return_value = mock_pub

        body, status, _ = publish_mod.handle_publish(
            _Req(
                {"type": "com.acs.test", "source": "/svc", "subject": "u1", "data": {"a": 1}},
                {"Authorization": "Bearer t"},
            )
        )
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body).get("ok"))

    @patch("handlers.publish.verify_platform_request", return_value=(None, ({"error": "missing platform bearer token"}, 401)))
    def test_publish_401(self, _v):
        body, status, _ = publish_mod.handle_publish(_Req({}))
        self.assertEqual(status, 401)


if __name__ == "__main__":
    unittest.main()

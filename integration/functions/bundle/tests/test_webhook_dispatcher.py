import json
import unittest

from dispatcher.webhook_dispatcher import handle_webhook_v1_request
from providers.provider_registry import PROVIDER_REGISTRY


class WebhookDispatcherTest(unittest.TestCase):
    def test_unknown_provider_404(self):
        class R:
            pass

        raw, status, _ = handle_webhook_v1_request(R(), "not_a_provider")
        self.assertEqual(status, 404)
        body = json.loads(raw)
        self.assertIn("unknown provider", body.get("error", ""))

    def test_known_provider_delegates(self):
        calls = []

        class R:
            pass

        class FakeProv:
            def webhook_ingress(self, request):
                calls.append(request)
                return ("{}", 200, {})

        prev = PROVIDER_REGISTRY["followupboss"]
        try:
            PROVIDER_REGISTRY["followupboss"] = FakeProv()
            _raw, status, _ = handle_webhook_v1_request(R(), "followupboss")
            self.assertEqual(status, 200)
            self.assertEqual(len(calls), 1)
        finally:
            PROVIDER_REGISTRY["followupboss"] = prev


if __name__ == "__main__":
    unittest.main()

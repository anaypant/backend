import json
import unittest
from unittest.mock import patch

from providers.followupboss import webhooks


class DummyReq:
    def __init__(self):
        self.args = {"connectionId": "u1"}
        self.headers = {"FUB-Signature": "sig"}

    def get_data(self, cache=False, as_text=False):
        return json.dumps({"eventId": "e1", "event": "peopleCreated", "uri": "https://api.followupboss.com/v1/people/1"}).encode("utf-8")


class WebhookIngestTest(unittest.TestCase):
    @patch("providers.followupboss.webhooks.update_event_status")
    @patch("providers.followupboss.webhooks.put_event_ledger", return_value=(True, {}))
    @patch("providers.followupboss.webhooks.send_state_to_core", return_value=({"state": {"metadata": {"outboundActions": []}}}, 200))
    @patch("providers.followupboss.webhooks.get_secret", return_value="xkey")
    @patch("providers.followupboss.webhooks._signature_ok", return_value=True)
    @patch("providers.followupboss.webhooks.load_fub_profile_by_connection_id", return_value=({}, {"auth": {"xSystemKeyRef": "env://FUB_X_SYSTEM_KEY"}}))
    def test_webhook_ingress_accepted(self, *_mocks):
        body, status, _ = webhooks.webhook_ingress(DummyReq())
        self.assertEqual(status, 200)
        self.assertIn("accepted", body)


if __name__ == "__main__":
    unittest.main()

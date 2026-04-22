import json
import unittest
from unittest.mock import patch

from providers.followupboss import webhooks


class DummyReq:
    def __init__(self, uid="u1"):
        self.args = {"connectionId": uid}
        self.headers = {"FUB-Signature": "sig"}

    def get_data(self, cache=False, as_text=False):
        return json.dumps(
            {"eventId": "e1", "event": "peopleCreated", "uri": "https://api.followupboss.com/v1/people/1"},
        ).encode("utf-8")


class WebhookExecutionPolicyTest(unittest.TestCase):
    @patch(
        "providers.followupboss.webhooks.load_fub_profile_by_connection_id",
        return_value=({"guardrailLevel": 0}, {"auth": {"xSystemKeyRef": "env://FUB_X_SYSTEM_KEY"}}),
    )
    @patch("providers.followupboss.webhooks._signature_ok", return_value=True)
    @patch("providers.followupboss.webhooks.get_secret", return_value="xkey")
    @patch(
        "providers.followupboss.webhooks.send_state_to_core",
        return_value=(
            {
                "state": {
                    "metadata": {
                        "outboundActions": [
                            {"name": "createNote", "payload": {"personId": 1, "body": "hello"}},
                        ],
                    },
                },
            },
            200,
        ),
    )
    @patch("providers.followupboss.webhooks.put_event_ledger", return_value=(True, {}))
    @patch("providers.followupboss.webhooks.update_event_status")
    @patch("providers.followupboss.webhooks.dispatch_provider_actions")
    @patch(
        "providers.followupboss.webhooks.merge_fub_person_from_api",
        return_value={"fubPersonSet": False, "skipped": "test"},
    )
    def test_analytical_skips_outbound_dispatch(
        self,
        _mock_merge,
        mock_dispatch,
        mock_update,
        mock_ledger,
        mock_send,
        mock_secret,
        mock_sig,
        mock_load_fub,
    ):
        body, status, _ = webhooks.webhook_ingress(DummyReq())
        self.assertEqual(status, 200)
        self.assertIn("accepted", body)
        mock_dispatch.assert_not_called()

    @patch(
        "providers.followupboss.webhooks.load_fub_profile_by_connection_id",
        return_value=({"guardrailLevel": 1}, {"auth": {"xSystemKeyRef": "env://FUB_X_SYSTEM_KEY"}}),
    )
    @patch("providers.followupboss.webhooks._signature_ok", return_value=True)
    @patch("providers.followupboss.webhooks.get_secret", return_value="xkey")
    @patch(
        "providers.followupboss.webhooks.send_state_to_core",
        return_value=(
            {
                "state": {
                    "metadata": {
                        "outboundActions": [
                            {"name": "createNote", "payload": {"personId": 1, "body": "hello"}},
                        ],
                    },
                },
            },
            200,
        ),
    )
    @patch("providers.followupboss.webhooks.put_event_ledger", return_value=(True, {}))
    @patch("providers.followupboss.webhooks.update_event_status")
    @patch("providers.followupboss.webhooks.dispatch_provider_actions")
    @patch(
        "providers.followupboss.webhooks.merge_fub_person_from_api",
        return_value={"fubPersonSet": False, "skipped": "test"},
    )
    def test_hands_on_calls_dispatch(
        self,
        _mock_merge,
        mock_dispatch,
        mock_update,
        mock_ledger,
        mock_send,
        mock_secret,
        mock_sig,
        mock_load_fub,
    ):
        mock_dispatch.return_value = {"ok": True, "results": []}
        body, status, _ = webhooks.webhook_ingress(DummyReq())
        self.assertEqual(status, 200)
        mock_dispatch.assert_called_once()


if __name__ == "__main__":
    unittest.main()

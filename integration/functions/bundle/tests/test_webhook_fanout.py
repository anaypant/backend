import json
import unittest
from unittest.mock import patch

from providers.followupboss import webhooks


class DummyReq:
    def __init__(self):
        self.args = {"connectionId": "u1"}
        self.headers = {"FUB-Signature": "sig"}

    def get_data(self, cache=False, as_text=False):
        return json.dumps(
            {"eventId": "e1", "event": "peopleCreated", "uri": "https://api.followupboss.com/v1/people/1"},
        ).encode("utf-8")


class WebhookFanoutTest(unittest.TestCase):
    @patch("providers.followupboss.webhooks.update_event_status")
    @patch("providers.followupboss.webhooks.put_event_ledger", return_value=(True, {}))
    @patch("providers.followupboss.webhooks.dispatch_provider_actions")
    @patch("providers.followupboss.webhooks.resolve_workflow_ids_for_webhook", return_value=["wf_a", "wf_b"])
    @patch(
        "providers.followupboss.webhooks.send_state_to_core",
        return_value=({"state": {"metadata": {"outboundActions": []}}}, 200),
    )
    @patch("providers.followupboss.webhooks.get_secret", return_value="xkey")
    @patch("providers.followupboss.webhooks._signature_ok", return_value=True)
    @patch("providers.followupboss.webhooks.load_fub_profile_by_connection_id", return_value=({}, {"auth": {"xSystemKeyRef": "env://FUB_X_SYSTEM_KEY"}}))
    @patch(
        "providers.followupboss.webhooks.merge_fub_person_from_api",
        return_value={"fubPersonSet": False, "skipped": "test"},
    )
    def test_two_workflows_invoke_core_twice(
        self,
        _mock_update,
        _mock_ledger,
        _mock_dispatch,
        _mock_resolve,
        mock_send,
        _mock_secret,
        _mock_sig,
        _mock_load,
        _mock_merge,
    ):
        raw, status, _ = webhooks.webhook_ingress(DummyReq())
        self.assertEqual(status, 200)
        self.assertEqual(mock_send.call_count, 2)
        wf_args = [c[1]["workflow_id"] for c in mock_send.call_args_list]
        self.assertEqual(wf_args, ["wf_a", "wf_b"])
        body = json.loads(raw)
        self.assertIn("webhook_dispatch", body)
        self.assertEqual(len(body.get("webhook_dispatch", [])), 2)


if __name__ == "__main__":
    unittest.main()

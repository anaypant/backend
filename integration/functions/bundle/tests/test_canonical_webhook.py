import unittest

from schema.canonical_webhook import (
    build_canonical_webhook_event_v1,
    to_acs_state_v1,
    validate_canonical_webhook_event_v1,
)


class CanonicalWebhookTest(unittest.TestCase):
    def test_build_and_validate_round_trip(self):
        raw = {"eventId": "e99", "event": "peopleUpdated", "uri": "https://api.followupboss.com/v1/people/3"}
        c = build_canonical_webhook_event_v1(
            provider="followupboss",
            connection_id="conn1",
            raw_provider_body=raw,
        )
        ok, err = validate_canonical_webhook_event_v1(c)
        self.assertTrue(ok, err)
        self.assertEqual(c["eventType"], "peopleUpdated")
        self.assertEqual(c["connectionId"], "conn1")

    def test_to_acs_state_matches_contract_shape(self):
        raw = {"eventId": "e1", "event": "peopleCreated", "x": 1}
        c = build_canonical_webhook_event_v1(
            provider="followupboss",
            connection_id="uid",
            raw_provider_body=raw,
        )
        st = to_acs_state_v1(c, connection_id="uid")
        self.assertEqual(st["state_version"], 1)
        self.assertEqual(st["correlation_id"], "e1")
        self.assertEqual(st["user_id"], "uid")
        self.assertEqual(st["source"]["provider"], "followupboss")
        self.assertEqual(st["source"]["event_type"], "peopleCreated")
        self.assertEqual(st["payload"]["x"], 1)
        cw = (st.get("metadata") or {}).get("canonical_webhook")
        self.assertIsInstance(cw, dict)
        self.assertEqual(cw.get("eventType"), "peopleCreated")


if __name__ == "__main__":
    unittest.main()

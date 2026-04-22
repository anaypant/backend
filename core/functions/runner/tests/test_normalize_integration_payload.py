import unittest

from workflows import normalize_integration_payload


class NormalizeIntegrationPayloadTest(unittest.TestCase):
    def test_followupboss_path_style_uri(self):
        acs = {
            "source": {"provider": "followupboss", "event_type": "peopleCreated"},
            "payload": {
                "event": "peopleCreated",
                "uri": "https://api.followupboss.com/v1/people/42",
            },
        }
        n = normalize_integration_payload.normalize_contact(acs)
        self.assertEqual(n["person_id"], 42)

    def test_followupboss_query_style_uri(self):
        acs = {
            "source": {"provider": "followupboss", "event_type": "peopleCreated"},
            "payload": {
                "event": "peopleCreated",
                "uri": "https://api.followupboss.com/v1/people?id=99",
            },
        }
        n = normalize_integration_payload.normalize_contact(acs)
        self.assertEqual(n["person_id"], 99)

    def test_followupboss_resource_ids_fallback(self):
        acs = {
            "source": {"provider": "followupboss", "event_type": "peopleCreated"},
            "payload": {
                "event": "peopleCreated",
                "uri": "https://example.com/unrelated",
                "resourceIds": [55],
            },
        }
        n = normalize_integration_payload.normalize_contact(acs)
        self.assertEqual(n["person_id"], 55)


if __name__ == "__main__":
    unittest.main()

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

    def test_followupboss_fub_person_enriches_contact(self):
        acs = {
            "source": {"provider": "followupboss", "event_type": "peopleCreated"},
            "payload": {
                "event": "peopleCreated",
                "uri": "https://api.followupboss.com/v1/people/12",
                "fubPerson": {
                    "id": 12,
                    "firstName": "Ada",
                    "lastName": "Lovelace",
                    "emails": [{"value": "ada@example.com"}],
                    "phones": [{"value": "+15551234567"}],
                },
            },
        }
        n = normalize_integration_payload.normalize_contact(acs)
        self.assertEqual(n["person_id"], 12)
        self.assertEqual(n["display_name"], "Ada Lovelace")
        self.assertEqual(n["emails"], ["ada@example.com"])
        self.assertEqual(n["phones"], ["+15551234567"])

    def test_followupboss_no_person_id_when_unresolvable(self):
        acs = {
            "source": {"provider": "followupboss", "event_type": "peopleCreated"},
            "payload": {
                "event": "peopleCreated",
                "uri": "https://example.com/not-a-person-endpoint",
            },
        }
        n = normalize_integration_payload.normalize_contact(acs)
        self.assertIsNone(n.get("person_id"))
        self.assertEqual(n.get("external_person_id"), "")


if __name__ == "__main__":
    unittest.main()

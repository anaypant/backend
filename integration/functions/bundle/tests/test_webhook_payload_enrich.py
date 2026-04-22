import unittest

from providers.followupboss.fub_payload_person_id import person_id_from_fub_webhook_payload


class WebhookPayloadEnrichTest(unittest.TestCase):
    def test_person_id_from_resource_ids_only(self):
        self.assertEqual(
            person_id_from_fub_webhook_payload({"resourceIds": [153], "event": "peopleCreated"}),
            153,
        )

    def test_person_id_from_path_uri(self):
        self.assertEqual(
            person_id_from_fub_webhook_payload(
                {"uri": "https://api.followupboss.com/v1/people/9", "event": "peopleCreated"},
            ),
            9,
        )

    def test_person_id_from_query_uri(self):
        self.assertEqual(
            person_id_from_fub_webhook_payload(
                {"uri": "https://api.followupboss.com/v1/people?id=22", "event": "peopleCreated"},
            ),
            22,
        )


if __name__ == "__main__":
    unittest.main()

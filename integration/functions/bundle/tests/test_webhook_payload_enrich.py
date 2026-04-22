import sys
import types
import unittest
from unittest.mock import MagicMock, patch


def _ensure_google_cloud_secretmanager_stub() -> None:
    """Local unittest imports ``providers.*`` → ``FubClient`` → ``secret_repo`` → Secret Manager."""
    sm = types.ModuleType("google.cloud.secretmanager")

    class SecretManagerServiceClient:  # pragma: no cover - stub for import only
        pass

    sm.SecretManagerServiceClient = SecretManagerServiceClient
    sys.modules["google.cloud.secretmanager"] = sm
    gc = sys.modules.get("google.cloud")
    if gc is None:
        gc = types.ModuleType("google.cloud")
        sys.modules["google.cloud"] = gc
    setattr(gc, "secretmanager", sm)


_ensure_google_cloud_secretmanager_stub()

from providers.followupboss.fub_payload_person_id import person_id_from_fub_webhook_payload
from providers.followupboss.webhook_payload_enrich import merge_fub_person_from_api


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


class MergeFubPersonFromApiTest(unittest.TestCase):
    @patch("providers.followupboss.oauth.refresh_fub_oauth_tokens_for_uid")
    @patch("providers.followupboss.webhook_payload_enrich.FubClient")
    def test_uri_401_refresh_then_retry_ok(self, fc_cls, refresh):
        refresh.return_value = ({}, 200)
        inst = MagicMock()
        inst.get_by_uri.side_effect = [({}, 401), ({"id": 7, "firstName": "X"}, 200)]
        fc_cls.return_value = inst
        payload: dict = {"event": "peopleCreated", "uri": "https://api.followupboss.com/v1/people/7"}
        st = merge_fub_person_from_api("uid1", {}, payload)
        self.assertTrue(st["fubPersonSet"])
        self.assertEqual(payload["fubPerson"]["id"], 7)
        self.assertTrue(st["oauthRefreshed"])
        refresh.assert_called_once()
        self.assertEqual(inst.get_by_uri.call_count, 2)

    @patch("providers.followupboss.oauth.refresh_fub_oauth_tokens_for_uid")
    @patch("providers.followupboss.webhook_payload_enrich.FubClient")
    def test_single_refresh_attempt_across_uri_and_person_401(self, fc_cls, refresh):
        refresh.return_value = ({"error": "bad"}, 400)
        inst = MagicMock()
        inst.get_by_uri.return_value = ({}, 401)
        inst.get_person.return_value = ({}, 401)
        fc_cls.return_value = inst
        payload: dict = {
            "event": "peopleCreated",
            "uri": "https://api.followupboss.com/v1/people?id=3",
            "resourceIds": [3],
        }
        st = merge_fub_person_from_api("uid2", {}, payload)
        self.assertFalse(st["fubPersonSet"])
        self.assertNotIn("fubPerson", payload)
        refresh.assert_called_once()

    @patch("providers.followupboss.oauth.refresh_fub_oauth_tokens_for_uid")
    @patch("providers.followupboss.webhook_payload_enrich.FubClient")
    def test_uri_non_401_fallback_get_person(self, fc_cls, refresh):
        inst = MagicMock()
        inst.get_by_uri.return_value = ({}, 404)
        inst.get_person.return_value = ({"id": 2, "firstName": "Z"}, 200)
        fc_cls.return_value = inst
        payload: dict = {"event": "peopleUpdated", "uri": "https://x/bad", "resourceIds": [2]}
        st = merge_fub_person_from_api("uid3", {}, payload)
        self.assertTrue(st["fubPersonSet"])
        self.assertEqual(st["via"], "person_id")
        inst.get_person.assert_called_once_with(2)
        refresh.assert_not_called()


if __name__ == "__main__":
    unittest.main()

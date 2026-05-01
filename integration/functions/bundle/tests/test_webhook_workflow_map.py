import unittest

from dispatcher.webhook_workflow_map import (
    event_type_alias_keys,
    resolve_default_workflow_id,
    resolve_workflow_ids_for_webhook,
)


class WebhookWorkflowMapTest(unittest.TestCase):
    def test_people_created_aliases(self):
        want = ["contact.enrichment_v1", "lead.scoring_v1"]
        for et in ("peopleCreated", "people_created", "PeopleCreated"):
            ids = resolve_workflow_ids_for_webhook("followupboss", et, explicit_workflow_id=None, policy={})
            self.assertEqual(ids, want, msg=et)

    def test_people_updated_runs_intel_delta_then_scoring(self):
        for et in ("peopleUpdated", "people_updated", "PeopleUpdated"):
            ids = resolve_workflow_ids_for_webhook("followupboss", et, explicit_workflow_id=None, policy={})
            self.assertEqual(
                ids,
                ["contact.intel_delta_v1", "lead.scoring_v1"],
                msg=et,
            )

    def test_explicit_overrides_table(self):
        ids = resolve_workflow_ids_for_webhook(
            "followupboss",
            "peopleCreated",
            explicit_workflow_id="demo.joke_to_profile_v1",
            policy={},
        )
        self.assertEqual(ids, ["demo.joke_to_profile_v1"])

    def test_unknown_event_empty(self):
        self.assertEqual(
            resolve_workflow_ids_for_webhook("followupboss", "notesCreated", explicit_workflow_id=None, policy={}),
            [],
        )

    def test_resolve_default_backward_compat(self):
        self.assertEqual(resolve_default_workflow_id("peopleCreated", {}), "contact.enrichment_v1")
        self.assertIsNone(resolve_default_workflow_id("notesCreated", {}))

    def test_event_type_alias_keys_nonempty(self):
        keys = event_type_alias_keys("peopleCreated")
        self.assertIn("peopleCreated", keys)
        self.assertIn("people_created", keys)


if __name__ == "__main__":
    unittest.main()

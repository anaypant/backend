import unittest

from dispatcher.workflow_router import resolve_default_workflow_id


class WorkflowRouterTest(unittest.TestCase):
    def test_person_events_route_to_enrichment(self):
        self.assertEqual(
            resolve_default_workflow_id("peopleCreated", {}),
            "contact.enrichment_v1",
        )
        self.assertEqual(
            resolve_default_workflow_id("peopleUpdated", {}),
            "contact.enrichment_v1",
        )

    def test_unknown_event_stub(self):
        self.assertIsNone(resolve_default_workflow_id("notesCreated", {}))
        self.assertIsNone(resolve_default_workflow_id("", {}))


if __name__ == "__main__":
    unittest.main()

import unittest

from workflows import registry as wf_registry


class WorkflowPolicyRoutingTest(unittest.TestCase):
    def test_contact_enrichment_registered(self):
        self.assertTrue(wf_registry.is_registered("contact.enrichment_v1"))

    def test_migration_import_leads_registered(self):
        self.assertTrue(wf_registry.is_registered("migration.import_leads_v1"))

    def test_demo_allowed_in_analytical(self):
        acs: dict = {
            "metadata": {
                "execution_policy": {
                    "volatile_external_allowed": False,
                    "integration_maintenance_allowed": True,
                }
            }
        }
        self.assertEqual(
            wf_registry.resolve_registered_workflow_id("demo.joke_to_profile_v1", acs),
            "demo.joke_to_profile_v1",
        )

    def test_substitutes_volatile_workflow_in_analytical(self):
        acs: dict = {
            "metadata": {
                "execution_policy": {
                    "volatile_external_allowed": False,
                    "integration_maintenance_allowed": True,
                }
            }
        }
        orig = wf_registry.WORKFLOW_CAPS["demo.joke_to_profile_v1"]
        try:
            wf_registry.WORKFLOW_CAPS["demo.joke_to_profile_v1"] = {
                "volatile_external": True,
                "requires_integration_maintenance": False,
            }
            wid = wf_registry.resolve_registered_workflow_id("demo.joke_to_profile_v1", acs)
            self.assertEqual(wid, "analytical.stub_v1")
            wr = acs.get("metadata", {}).get("workflow_routing")
            self.assertIsInstance(wr, dict)
            self.assertEqual(wr.get("requested_workflow_id"), "demo.joke_to_profile_v1")
            self.assertEqual(wr.get("substituted_workflow_id"), "analytical.stub_v1")
        finally:
            wf_registry.WORKFLOW_CAPS["demo.joke_to_profile_v1"] = orig

    def test_analytical_stub_completes(self):
        acs: dict = {
            "state_version": 1,
            "correlation_id": "c1",
            "source": {"provider": "test", "event_type": "x"},
            "payload": {},
            "user_id": "u1",
        }
        out = wf_registry.run_workflow("analytical.stub_v1", acs)
        meta = out.get("metadata") or {}
        core = meta.get("core") if isinstance(meta.get("core"), dict) else {}
        self.assertEqual(core.get("status"), "completed")
        self.assertEqual(core.get("workflow_id"), "analytical.stub_v1")


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import patch

from workflows import registry as wf_registry
from workflows.migrations.provider_maps import followupboss_lead
class FollowupbossLeadMapTest(unittest.TestCase):
    def test_roundtrip_core_fields(self):
        fub = {
            "id": 99,
            "firstName": "A",
            "lastName": "B",
            "emails": [{"value": "a@b.co", "isPrimary": True}],
            "phones": [{"value": "555", "type": "mobile"}],
        }
        internal = followupboss_lead.followupboss_person_to_internal(fub)
        self.assertIsNotNone(internal)
        assert internal is not None
        self.assertEqual(internal["canonicalLeadId"], "followupboss_99")
        back = followupboss_lead.internal_to_followupboss_person_upsert(internal)
        self.assertEqual(back.get("firstName"), "A")
        self.assertEqual(back.get("lastName"), "B")


class MigrationImportLeadsWorkflowTest(unittest.TestCase):
    @patch("workflows.migrations.import_leads_v1.integration_bridge.to_providers")
    @patch("workflows.migrations.import_leads_v1.db_internal.upsert_merge")
    def test_import_happy_path(self, mock_upsert, mock_to):
        mock_upsert.return_value = ({}, 200)
        mock_to.return_value = ({"provider_states": []}, 200)
        acs = {
            "state_version": 1,
            "correlation_id": "m1",
            "user_id": "u1",
            "source": {"provider": "followupboss", "event_type": "x"},
            "payload": {
                "source_batches": [
                    {
                        "provider": "followupboss",
                        "records": [{"id": 7, "firstName": "X", "lastName": "Y"}],
                    }
                ]
            },
        }
        out = wf_registry.run_workflow("migration.import_leads_v1", acs)
        meta = out.get("metadata") or {}
        core = meta.get("core") if isinstance(meta.get("core"), dict) else {}
        self.assertEqual(core.get("status"), "completed")
        mig = meta.get("migrationImport") if isinstance(meta.get("migrationImport"), dict) else {}
        self.assertEqual(mig.get("persistedCount"), 1)
        mock_upsert.assert_called_once()
        mock_to.assert_called_once()

    @patch("workflows.migrations.import_leads_v1.integration_bridge.to_providers")
    @patch("workflows.migrations.import_leads_v1.integration_bridge.from_providers")
    @patch("workflows.migrations.import_leads_v1.db_internal.upsert_merge")
    def test_import_via_provider_load(self, mock_upsert, mock_from, mock_to):
        mock_upsert.return_value = ({}, 200)
        mock_from.return_value = (
            {
                "acs_patch": {
                    "source": {"provider": "followupboss", "event_type": "state_bridge.provider_load"},
                    "payload": {
                        "source_batches": [
                            {
                                "provider": "followupboss",
                                "records": [{"id": 7, "firstName": "X", "lastName": "Y"}],
                            }
                        ]
                    },
                }
            },
            200,
        )
        mock_to.return_value = ({"provider_states": [{"provider": "followupboss", "kind": "migration_import_summary"}]}, 200)
        acs = {
            "state_version": 1,
            "correlation_id": "m2",
            "user_id": "u1",
            "source": {"provider": "followupboss", "event_type": "x"},
            "payload": {
                "providerLoad": [
                    {"provider": "followupboss", "kind": "people_list_request", "payload": {"batchSize": 10}}
                ]
            },
        }
        out = wf_registry.run_workflow("migration.import_leads_v1", acs)
        meta = out.get("metadata") or {}
        core = meta.get("core") if isinstance(meta.get("core"), dict) else {}
        self.assertEqual(core.get("status"), "completed")
        mock_from.assert_called_once()
        ic = meta.get("integrationContext") if isinstance(meta.get("integrationContext"), dict) else {}
        self.assertTrue(ic.get("fromProvidersApplied"))
        unload = ic.get("providerUnload")
        self.assertIsInstance(unload, list)


if __name__ == "__main__":
    unittest.main()

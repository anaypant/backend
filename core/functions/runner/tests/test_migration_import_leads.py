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

    @patch("workflows.migrations.import_leads_v1.integration_bridge.to_providers")
    @patch("workflows.migrations.import_leads_v1.integration_bridge.from_providers")
    @patch("workflows.migrations.import_leads_v1.db_internal.upsert_merge")
    def test_import_followupboss_auto_list_paginates(self, mock_upsert, mock_from, mock_to):
        mock_upsert.return_value = ({}, 200)
        mock_to.return_value = ({"provider_states": []}, 200)

        def side_effect(_uid, blocks):
            payload = blocks[0].get("payload") if blocks and isinstance(blocks[0], dict) else {}
            if isinstance(payload, dict) and payload.get("next") == "page2":
                return (
                    {
                        "acs_patch": {
                            "payload": {
                                "source_batches": [
                                    {
                                        "provider": "followupboss",
                                        "records": [{"id": 2, "firstName": "B", "lastName": "Two"}],
                                    }
                                ],
                                "_integration": {"followupbossPeopleMetadata": {}},
                            },
                        }
                    },
                    200,
                )
            return (
                {
                    "acs_patch": {
                        "payload": {
                            "source_batches": [
                                {
                                    "provider": "followupboss",
                                    "records": [{"id": 1, "firstName": "A", "lastName": "One"}],
                                }
                            ],
                            "_integration": {"followupbossPeopleMetadata": {"next": "page2"}},
                        },
                    }
                },
                200,
            )

        mock_from.side_effect = side_effect
        acs = {
            "state_version": 1,
            "correlation_id": "m3",
            "user_id": "u1",
            "source": {"provider": "followupboss", "event_type": "account.migrate"},
            "payload": {},
        }
        out = wf_registry.run_workflow("migration.import_leads_v1", acs)
        meta = out.get("metadata") or {}
        core = meta.get("core") if isinstance(meta.get("core"), dict) else {}
        self.assertEqual(core.get("status"), "completed")
        self.assertEqual(mock_from.call_count, 2)
        self.assertEqual(mock_upsert.call_count, 2)
        mig = meta.get("migrationImport") if isinstance(meta.get("migrationImport"), dict) else {}
        self.assertEqual(mig.get("followupbossListPagesFetched"), 2)
        self.assertEqual(mig.get("followupbossPeopleRowsSeen"), 2)

    @patch("workflows.migrations.import_leads_v1.integration_bridge.to_providers")
    @patch("workflows.migrations.import_leads_v1.integration_bridge.from_providers")
    @patch("workflows.migrations.import_leads_v1.db_internal.upsert_merge")
    def test_import_person_id_refresh_via_fub_person(self, mock_upsert, mock_from, mock_to):
        mock_upsert.return_value = ({}, 200)
        mock_to.return_value = ({"provider_states": []}, 200)
        mock_from.return_value = (
            {
                "acs_patch": {
                    "source": {"provider": "followupboss", "event_type": "state_bridge.person_by_id"},
                    "payload": {
                        "fubPerson": {"id": 42, "firstName": "Pat", "lastName": "FortyTwo"},
                        "_integration": {"fubPersonFetch": {"personId": 42, "ok": True}},
                    },
                }
            },
            200,
        )
        acs = {
            "state_version": 1,
            "correlation_id": "m4",
            "user_id": "u1",
            "source": {"provider": "followupboss", "event_type": "refresh"},
            "payload": {"personId": 42},
        }
        out = wf_registry.run_workflow("migration.import_leads_v1", acs)
        meta = out.get("metadata") or {}
        core = meta.get("core") if isinstance(meta.get("core"), dict) else {}
        self.assertEqual(core.get("status"), "completed")
        mock_from.assert_called_once()
        args, _kw = mock_from.call_args
        blocks = args[1]
        self.assertEqual(blocks[0].get("kind"), "person_by_id")
        self.assertEqual(mock_upsert.call_count, 1)
        up_args = mock_upsert.call_args[0]
        self.assertIn("shardKey", up_args[1])
        self.assertEqual(up_args[1].get("ownerId"), "u1")


if __name__ == "__main__":
    unittest.main()

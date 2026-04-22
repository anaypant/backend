import json
import unittest
from unittest.mock import patch

from workflows import registry as wf_registry
from workflows import normalize_integration_payload


class ContactEnrichmentWorkflowTest(unittest.TestCase):
    def test_normalize_followupboss_uri(self):
        acs = {
            "source": {"provider": "followupboss", "event_type": "peopleCreated"},
            "payload": {
                "eventId": "e1",
                "event": "peopleCreated",
                "uri": "https://api.followupboss.com/v1/people/42",
            },
        }
        n = normalize_integration_payload.normalize_contact(acs)
        self.assertEqual(n["provider"], "followupboss")
        self.assertEqual(n["person_id"], 42)
        self.assertEqual(n["external_person_id"], "42")

    @patch("workflows.contact_enrichment_v1.tool_registry.run_tool")
    @patch("workflows.contact_enrichment_v1.llm_internal.complete")
    @patch("workflows.contact_enrichment_v1.web_research_internal.research_query_to_summary")
    @patch("workflows.contact_enrichment_v1.db_internal.read_document")
    def test_enrichment_happy_path_volatile_send(
        self,
        mock_read,
        mock_research,
        mock_llm,
        mock_run_tool,
    ):
        def _read(path: str, **kwargs):
            if path == "Realtors/u1":
                return {"data": {"displayName": "Agent"}}, 200
            if "InternalClients" in path:
                return {"error": "not found"}, 404
            return {"error": "unexpected"}, 500

        mock_read.side_effect = _read
        mock_research.return_value = (
            {"summary": "Local market active.", "sources": [], "mode": "llm_structured"},
            200,
        )
        mock_llm.return_value = (
            {"text": json.dumps({"updates": {"suggested_note": "Note from ACS enrichment."}})},
            200,
        )
        mock_run_tool.return_value = ({"ok": True, "mode": "deferred"}, 200)

        acs = {
            "state_version": 1,
            "correlation_id": "c-enrich",
            "source": {"provider": "followupboss", "event_type": "peopleCreated"},
            "payload": {
                "eventId": "e1",
                "event": "peopleCreated",
                "uri": "https://api.followupboss.com/v1/people/7",
                "fubPerson": {
                    "id": 7,
                    "firstName": "Pat",
                    "lastName": "Seven",
                    "emails": [{"value": "pat@example.com"}],
                },
            },
            "user_id": "u1",
            "metadata": {
                "execution_policy": {"volatile_external_allowed": True},
            },
        }
        out = wf_registry.run_workflow("contact.enrichment_v1", acs)
        meta = out.get("metadata") or {}
        core = meta.get("core") if isinstance(meta.get("core"), dict) else {}
        self.assertEqual(core.get("status"), "completed")
        oa = meta.get("outboundActions")
        self.assertIsInstance(oa, list)
        self.assertEqual(len(oa), 1)
        self.assertEqual(oa[0].get("name"), "createNote")
        self.assertEqual(oa[0].get("payload", {}).get("personId"), 7)
        mock_run_tool.assert_called_once()
        audit = meta.get("workflowAudit")
        self.assertIsInstance(audit, dict)
        self.assertEqual(audit.get("status"), "completed")
        self.assertGreaterEqual(audit.get("billing", {}).get("llm_calls", 0), 2)

    @patch("workflows.contact_enrichment_v1.tool_registry.run_tool")
    @patch("workflows.contact_enrichment_v1.llm_internal.complete")
    @patch("workflows.contact_enrichment_v1.web_research_internal.research_query_to_summary")
    @patch("workflows.contact_enrichment_v1.db_internal.read_document")
    def test_enrichment_accepts_top_level_suggested_note_in_json(
        self,
        mock_read,
        mock_research,
        mock_llm,
        mock_run_tool,
    ):
        def _read(path: str, **kwargs):
            if path == "Realtors/u1":
                return {"data": {"displayName": "Agent"}}, 200
            if "InternalClients" in path:
                return {"error": "not found"}, 404
            return {"error": "unexpected"}, 500

        mock_read.side_effect = _read
        mock_research.return_value = ({"summary": "", "sources": [], "mode": "stub"}, 200)
        mock_llm.return_value = (
            {"text": json.dumps({"suggested_note": "Note from flat JSON.", "confidence": "high"})},
            200,
        )
        mock_run_tool.return_value = ({"ok": True}, 200)

        acs = {
            "state_version": 1,
            "correlation_id": "c-flat",
            "source": {"provider": "followupboss", "event_type": "peopleCreated"},
            "payload": {
                "eventId": "e1",
                "event": "peopleCreated",
                "uri": "https://api.followupboss.com/v1/people/7",
                "fubPerson": {"id": 7, "firstName": "Pat", "lastName": "Seven"},
            },
            "user_id": "u1",
            "metadata": {"execution_policy": {"volatile_external_allowed": True}},
        }
        out = wf_registry.run_workflow("contact.enrichment_v1", acs)
        meta = out.get("metadata") or {}
        oa = meta.get("outboundActions")
        self.assertIsInstance(oa, list)
        self.assertEqual(len(oa), 1)
        self.assertEqual(oa[0].get("payload", {}).get("body"), "Note from flat JSON.")
        syn = (meta.get("contactEnrichment") or {}).get("synthesis") or {}
        self.assertEqual(syn.get("coercion"), "top_level_fields")

    @patch("workflows.contact_enrichment_v1.tool_registry.run_tool")
    @patch("workflows.contact_enrichment_v1.llm_internal.complete")
    @patch("workflows.contact_enrichment_v1.web_research_internal.research_query_to_summary")
    @patch("workflows.contact_enrichment_v1.db_internal.read_document")
    def test_enrichment_empty_updates_gets_fallback_note(
        self,
        mock_read,
        mock_research,
        mock_llm,
        mock_run_tool,
    ):
        def _read(path: str, **kwargs):
            if path == "Realtors/u1":
                return {"data": {"displayName": "Agent"}}, 200
            if "InternalClients" in path:
                return {"error": "not found"}, 404
            return {"error": "unexpected"}, 500

        mock_read.side_effect = _read
        mock_research.return_value = ({"summary": "", "sources": [], "mode": "stub"}, 200)
        mock_llm.return_value = (
            {"text": json.dumps({"updates": {}, "confidence": "low", "rationale": "none"})},
            200,
        )
        mock_run_tool.return_value = ({"ok": True}, 200)

        acs = {
            "state_version": 1,
            "correlation_id": "c-fallback",
            "source": {"provider": "followupboss", "event_type": "peopleCreated"},
            "payload": {
                "eventId": "e1",
                "event": "peopleCreated",
                "uri": "https://api.followupboss.com/v1/people/99",
                "fubPerson": {"id": 99, "firstName": "Nada", "lastName": "Empty"},
            },
            "user_id": "u1",
            "metadata": {"execution_policy": {"volatile_external_allowed": True}},
        }
        out = wf_registry.run_workflow("contact.enrichment_v1", acs)
        meta = out.get("metadata") or {}
        oa = meta.get("outboundActions")
        self.assertEqual(len(oa), 1)
        body = oa[0].get("payload", {}).get("body") or ""
        self.assertIn("ACS enrichment", body)
        self.assertIn("Nada", body)
        syn = (meta.get("contactEnrichment") or {}).get("synthesis") or {}
        self.assertTrue(syn.get("fallback_note"))

    @patch("workflows.contact_enrichment_v1.db_internal.read_document")
    def test_duplicate_internal_client_short_circuits(self, mock_read):
        def _read(path: str, **kwargs):
            if path == "Realtors/u1":
                return {"data": {}}, 200
            if "InternalClients" in path:
                return {"data": {"ownerUid": "u1"}}, 200
            return {"error": "not found"}, 404

        mock_read.side_effect = _read

        acs = {
            "state_version": 1,
            "correlation_id": "c-dup",
            "source": {"provider": "followupboss", "event_type": "peopleCreated"},
            "payload": {
                "eventId": "e1",
                "event": "peopleCreated",
                "uri": "https://api.followupboss.com/v1/people/2",
            },
            "user_id": "u1",
            "metadata": {},
        }
        out = wf_registry.run_workflow("contact.enrichment_v1", acs)
        meta = out.get("metadata") or {}
        core = meta.get("core") if isinstance(meta.get("core"), dict) else {}
        self.assertEqual(core.get("status"), "completed")
        self.assertEqual(core.get("phase"), "skipped_duplicate_internal_client")
        self.assertEqual(mock_read.call_count, 2)


if __name__ == "__main__":
    unittest.main()

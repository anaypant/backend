"""Unit tests for lead intelligence CLI helpers (doc ids + FUB webhook body shape)."""

from __future__ import annotations

import unittest

from lead_intel_helpers import (
    canonical_lead_doc_id,
    fub_webhook_minimal_body,
    internal_client_doc_id,
    normalize_fub_webhook_event,
)


class LeadIntelHelpersTest(unittest.TestCase):
    def test_internal_client_doc_id_matches_core_contract(self) -> None:
        self.assertEqual(
            internal_client_doc_id(provider="followupboss", external_person_id="153"),
            "followupboss_153",
        )
        self.assertEqual(
            internal_client_doc_id(provider="followupboss", external_person_id=153),
            "followupboss_153",
        )

    def test_canonical_lead_doc_id(self) -> None:
        self.assertEqual(canonical_lead_doc_id(42), "followupboss_42")

    def test_normalize_fub_webhook_event(self) -> None:
        self.assertEqual(normalize_fub_webhook_event("personCreated"), "peopleCreated")
        self.assertEqual(normalize_fub_webhook_event("people_created"), "peopleCreated")
        self.assertEqual(normalize_fub_webhook_event("peopleUpdated"), "peopleUpdated")

    def test_fub_webhook_minimal_body(self) -> None:
        b = fub_webhook_minimal_body(event="peopleUpdated", person_id=999, event_id="fixed-id")
        self.assertEqual(b["event"], "peopleUpdated")
        self.assertEqual(b["eventId"], "fixed-id")
        self.assertEqual(b["resourceIds"], [999])
        self.assertIn("people?id=999", b["uri"])


if __name__ == "__main__":
    unittest.main()

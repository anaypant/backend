"""Unit tests for lead_lane_policy."""

import unittest

from clients.lead_lane_policy import (
    compute_lane,
    legacy_migration_merge_fields,
    resolve_lead_lane_auto_mode,
)


class LeadLanePolicyTest(unittest.TestCase):
    def test_resolve_mode_from_settings(self):
        self.assertEqual(resolve_lead_lane_auto_mode({"leadLaneAutoMode": "shadow"}), "shadow")
        self.assertEqual(resolve_lead_lane_auto_mode({}), "off")

    def test_pinned_skips_auto(self):
        d = {"glydeLaneUserPinned": True, "glydeLeadLane": "nurture", "glydeScore": 90}
        dec = compute_lane(d, {}, {})
        self.assertTrue(dec.skip_auto_write)
        self.assertEqual(dec.lane, "nurture")

    def test_hot_stays_active(self):
        d = {"glydeIsHot": True, "glydeScore": 10}
        dec = compute_lane(d, {}, {})
        self.assertEqual(dec.lane, "active")
        self.assertIn("hot_lead", dec.reason_codes)

    def test_very_low_score_nurture(self):
        d = {"glydeScore": 15, "lead": {"emails": ["a@b.com"]}}
        dec = compute_lane(d, {}, {})
        self.assertEqual(dec.lane, "nurture")

    def test_migration_quarantined_to_nurture(self):
        m = legacy_migration_merge_fields({"glydeQuarantined": True})
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m["glydeLeadLane"], "nurture")
        self.assertEqual(m["glydeLaneSource"], "migration")

    def test_migration_active_when_not_quarantined(self):
        m = legacy_migration_merge_fields({"glydeQuarantined": False})
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m["glydeLeadLane"], "active")

    def test_migration_noop_when_lane_set(self):
        self.assertIsNone(legacy_migration_merge_fields({"glydeLeadLane": "active"}))


if __name__ == "__main__":
    unittest.main()

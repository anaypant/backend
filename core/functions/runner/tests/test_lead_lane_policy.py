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

    def test_sparse_contact_cold_graph_nurture(self):
        d = {"glydeScore": 30, "lead": {"emails": [], "phones": []}}
        dec = compute_lane(d, {}, {})
        self.assertEqual(dec.lane, "nurture")
        self.assertIn("sparse_contact", dec.reason_codes)

    def test_sparse_contact_high_score_defaults_active(self):
        """No emails/phones but strong score — do not force nurture."""
        d = {"glydeScore": 80, "lead": {"emails": [], "phones": []}}
        dec = compute_lane(d, {}, {})
        self.assertEqual(dec.lane, "active")
        self.assertIn("default_active", dec.reason_codes)

    def test_phone_only_escapes_sparse_to_active_when_score_ok(self):
        d = {"glydeScore": 40, "lead": {"emails": [], "phones": ["+12025550199"]}}
        dec = compute_lane(d, {}, {})
        self.assertEqual(dec.lane, "active")

    def test_stale_low_score_nurture(self):
        old = "2020-01-01T00:00:00+00:00"
        d = {"glydeScore": 30, "lead": {"lastContacted": old, "emails": ["a@b.com"]}}
        dec = compute_lane(d, {}, {})
        self.assertEqual(dec.lane, "nurture")
        self.assertIn("low_score", dec.reason_codes)
        self.assertIn("stale_touch", dec.reason_codes)

    def test_score_boundary_very_low(self):
        d19 = {"glydeScore": 19, "lead": {"emails": ["x@y.com"], "phones": ["+1"]}}
        self.assertEqual(compute_lane(d19, {}, {}).lane, "nurture")
        d20 = {"glydeScore": 20, "lead": {"emails": ["x@y.com"], "phones": ["+1"]}}
        self.assertEqual(compute_lane(d20, {}, {}).lane, "active")

    def test_operator_nurture_pin_vs_unpinned_re_eval(self):
        pinned = {"glydeLaneUserPinned": True, "glydeLeadLane": "nurture", "glydeScore": 55}
        self.assertTrue(compute_lane(pinned, {}, {}).skip_auto_write)
        unpinned = {
            "glydeLaneUserPinned": False,
            "glydeLeadLane": "nurture",
            "glydeScore": 55,
            "lead": {"emails": ["a@b.com"]},
        }
        self.assertEqual(compute_lane(unpinned, {}, {}).lane, "active")
        self.assertFalse(compute_lane(unpinned, {}, {}).skip_auto_write)


if __name__ == "__main__":
    unittest.main()

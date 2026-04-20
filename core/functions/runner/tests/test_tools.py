import unittest

from tools import registry as tool_registry


class MergeRealtorProfileTest(unittest.TestCase):
    def test_unknown_tool(self):
        body, st = tool_registry.run_tool("nope", {}, acting_uid="u1")
        self.assertEqual(st, 400)
        self.assertIn("unknown", str(body.get("error", "")))

    def test_merge_requires_data_object(self):
        body, st = tool_registry.run_tool(
            "db.merge_realtor_profile",
            {},
            acting_uid="uid1",
        )
        self.assertEqual(st, 400)

    def test_volatile_tool_blocked_without_acs(self):
        orig = dict(tool_registry.TOOL_META.get("db.merge_realtor_profile") or {})
        try:
            tool_registry.TOOL_META["db.merge_realtor_profile"] = {"volatile_external": True}
            body, st = tool_registry.run_tool(
                "db.merge_realtor_profile",
                {"data": {"x": 1}, "uid": "u1"},
                acting_uid="u1",
            )
            self.assertEqual(st, 400)
            self.assertEqual(body.get("error"), "acs_required_for_volatile_tool")
        finally:
            tool_registry.TOOL_META["db.merge_realtor_profile"] = orig

    def test_volatile_tool_blocked_in_analytical(self):
        orig = dict(tool_registry.TOOL_META.get("db.merge_realtor_profile") or {})
        try:
            tool_registry.TOOL_META["db.merge_realtor_profile"] = {"volatile_external": True}
            acs = {"metadata": {"execution_policy": {"volatile_external_allowed": False}}}
            body, st = tool_registry.run_tool(
                "db.merge_realtor_profile",
                {"data": {"x": 1}, "uid": "u1"},
                acting_uid="u1",
                acs=acs,
            )
            self.assertEqual(st, 403)
            self.assertEqual(body.get("error"), "tool_blocked_by_execution_policy")
        finally:
            tool_registry.TOOL_META["db.merge_realtor_profile"] = orig


if __name__ == "__main__":
    unittest.main()

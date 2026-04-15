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


if __name__ == "__main__":
    unittest.main()

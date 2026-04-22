import unittest
from unittest.mock import patch

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

    @patch("tools.db_profile.db_internal.upsert_merge")
    def test_merge_realtor_profile_success(self, mock_upsert):
        mock_upsert.return_value = ({"ok": True, "revision": "r1"}, 200)
        body, st = tool_registry.run_tool(
            "db.merge_realtor_profile",
            {"uid": "agent_uid", "data": {"displayName": "Jane Agent"}},
            acting_uid="agent_uid",
        )
        self.assertEqual(st, 200)
        self.assertEqual(body.get("ok"), True)
        mock_upsert.assert_called_once_with(
            "Realtors/agent_uid",
            {"displayName": "Jane Agent"},
            acting_uid="agent_uid",
        )


class FollowupbossOutboundToolTest(unittest.TestCase):
    @patch("tools.integration_outbound.integration_bridge.apply_followupboss_outbound")
    def test_apply_followupboss_outbound_success_when_volatile_allowed(self, mock_apply):
        mock_apply.return_value = ({"ok": True, "applied": 1}, 200)
        acs = {"metadata": {"execution_policy": {"volatile_external_allowed": True}}}
        actions = [{"name": "createNote", "payload": {"personId": 1, "body": "Hi"}}]
        body, st = tool_registry.run_tool(
            "integration.apply_followupboss_outbound",
            {"uid": "crm_user", "actions": actions},
            acting_uid="crm_user",
            acs=acs,
        )
        self.assertEqual(st, 200)
        mock_apply.assert_called_once_with("crm_user", actions)

    def test_apply_followupboss_outbound_requires_acs_for_volatile_tool(self):
        body, st = tool_registry.run_tool(
            "integration.apply_followupboss_outbound",
            {"uid": "u1", "actions": [{"name": "createNote"}]},
            acting_uid="u1",
        )
        self.assertEqual(st, 400)
        self.assertEqual(body.get("error"), "acs_required_for_volatile_tool")

    def test_apply_followupboss_outbound_blocked_in_analytical_mode(self):
        acs = {"metadata": {"execution_policy": {"volatile_external_allowed": False}}}
        body, st = tool_registry.run_tool(
            "integration.apply_followupboss_outbound",
            {"uid": "u1", "actions": [{"name": "createNote", "payload": {}}]},
            acting_uid="u1",
            acs=acs,
        )
        self.assertEqual(st, 403)
        self.assertEqual(body.get("detail"), "volatile_external_not_allowed")

    @patch("tools.integration_outbound.integration_bridge.apply_followupboss_outbound")
    def test_apply_followupboss_outbound_empty_actions_returns_400_before_bridge(self, mock_apply):
        mock_apply.return_value = ({"error": "should not reach"}, 500)
        acs = {"metadata": {"execution_policy": {"volatile_external_allowed": True}}}
        body, st = tool_registry.run_tool(
            "integration.apply_followupboss_outbound",
            {"uid": "u1", "actions": []},
            acting_uid="u1",
            acs=acs,
        )
        self.assertEqual(st, 400)
        self.assertIn("non-empty", str(body.get("error", "")))
        mock_apply.assert_not_called()

    def test_apply_followupboss_outbound_requires_actions_list(self):
        acs = {"metadata": {"execution_policy": {"volatile_external_allowed": True}}}
        body, st = tool_registry.run_tool(
            "integration.apply_followupboss_outbound",
            {"uid": "u1", "actions": "not-a-list"},
            acting_uid="u1",
            acs=acs,
        )
        self.assertEqual(st, 400)
        self.assertIn("actions list", str(body.get("error", "")))


if __name__ == "__main__":
    unittest.main()

import unittest

from dispatcher import outbound_policy


class PartitionOutboundActionsTest(unittest.TestCase):
    def test_analytical_blocks_unknown_effect(self):
        actions = [{"name": "createNote", "payload": {"personId": 1, "body": "x"}}]
        to_apply, skipped = outbound_policy.partition_outbound_actions(
            actions,
            {"volatile_external_allowed": False},
        )
        self.assertEqual(to_apply, [])
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0].get("reason"), "volatile_external_blocked_by_policy")

    def test_hands_on_applies_volatile(self):
        actions = [{"name": "createNote", "payload": {"personId": 1, "body": "x"}}]
        to_apply, skipped = outbound_policy.partition_outbound_actions(
            actions,
            {"volatile_external_allowed": True},
        )
        self.assertEqual(len(to_apply), 1)
        self.assertEqual(skipped, [])

    def test_internal_effect_not_volatile(self):
        actions = [
            {"name": "noop", "payload": {}, "effect": "internal"},
        ]
        to_apply, skipped = outbound_policy.partition_outbound_actions(
            actions,
            {"volatile_external_allowed": False},
        )
        self.assertEqual(len(to_apply), 1)
        self.assertEqual(skipped, [])


if __name__ == "__main__":
    unittest.main()

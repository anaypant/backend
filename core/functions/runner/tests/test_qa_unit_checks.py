import unittest

from qa.unit_checks import run_all_unit_checks


class CoreQaUnitChecksTest(unittest.TestCase):
    def test_run_all_passes(self):
        out = run_all_unit_checks()
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(out["summary"]["failed"], 0)
        ids = [r["id"] for r in out["results"]]
        self.assertIn("normalize_integration_payload.fub_uri_path", ids)


if __name__ == "__main__":
    unittest.main()

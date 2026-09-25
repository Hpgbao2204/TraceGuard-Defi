import unittest
from eval.e5.tier_runner import run_tier1, run_tier2


class TestE5Runners(unittest.TestCase):
    def test_tier1_missing_adapter_is_not_testable(self):
        out = run_tier1()
        self.assertEqual(len(out["cases"]), 20)
        self.assertTrue(all(x["status"] in {"NOT_TESTABLE", "CLAIM_NOT_LOCALIZABLE"} for x in out["cases"]))

    def test_tier2_does_not_promote_without_tier1(self):
        out = run_tier2({"cases": [{"case_id": "x", "status": "NOT_TESTABLE"}]})
        self.assertEqual(out["cases"][0]["status"], "NOT_TESTABLE")


if __name__ == "__main__": unittest.main()

import unittest
from eval.e5.dose_response import build_dose_grid, classify_doses


class TestDoseResponse(unittest.TestCase):
    def test_revert_is_not_zero_harm(self):
        out = classify_doses([{"dose": 1, "execution": "REVERTED"}])
        self.assertEqual(out["status"], "NOT_TESTABLE")
        self.assertEqual(out["reverted"], 1)

    def test_executed_harm_is_summarized(self):
        out = classify_doses([{"dose": 1, "execution": "EXECUTED", "harm": -10}, {"dose": 0, "execution": "EXECUTED", "harm": 0}])
        self.assertEqual(out["status"], "OBSERVED")
        self.assertEqual(out["harm_min"], -10)

    def test_dose_grid_is_inclusive_and_deterministic(self):
        self.assertEqual(build_dose_grid(100, 0, 5), [100, 75, 50, 25, 0])


if __name__ == "__main__": unittest.main()

import unittest
from eval.e5.replay_adapter import gate3_target_check, run_tier1


class TestReplayAdapter(unittest.TestCase):
    def test_gate3_rejects_unclaimed_callee(self):
        out = gate3_target_check({"callee": "0x" + "11" * 20, "occurrences": [{"trace_index": 1}]}, {"victim_or_asset_addresses": ["0x" + "22" * 20]})
        self.assertEqual(out.reason, "TARGET_MISMATCH_CALLEE_NOT_CLAIMED_VICTIM_OR_ASSET")

    def test_backend_missing_is_not_testable(self):
        out = run_tier1({}, {"callee": "0x" + "11" * 20, "occurrences": [{"trace_index": 1}]}, {})
        self.assertEqual(out.execution_status, "NOT_TESTABLE")


if __name__ == "__main__": unittest.main()

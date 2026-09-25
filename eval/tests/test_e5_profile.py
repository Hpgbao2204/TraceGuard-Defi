import unittest
from eval.e5.profile import ddmin_restore, classify_profile, RestoreObservation


class TestE5Profile(unittest.TestCase):
    def test_ddmin_finds_minimal_pair(self):
        calls = []
        def oracle(s):
            calls.append(s)
            return {"a", "b"}.issubset(s)
        self.assertEqual(ddmin_restore({"a", "b", "c"}, oracle), frozenset({"a", "b"}))

    def test_missing_profile_is_not_testable(self):
        self.assertEqual(classify_profile("g0", [] )["outcome"], "NOT_TESTABLE")

    def test_incomplete_full_restore_is_not_testable(self):
        out = classify_profile("g0", [RestoreObservation(frozenset({"g1", "g2"}), "EXECUTED", True)])
        self.assertEqual(out["outcome"], "NO_TESTABLE_MECHANISM_EXPLAINS_HARM")


if __name__ == "__main__": unittest.main()

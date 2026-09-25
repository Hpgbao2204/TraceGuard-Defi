import unittest
from core.mutate import ArithmeticGuardInsert, ReentrancyGuardSubstitute


class TestE5Mutations(unittest.TestCase):
    def test_reentrancy_fails_closed_without_runtime(self):
        m = ReentrancyGuardSubstitute("0x" + "11" * 20, selector="0x12345678", descriptor={"match_count": 1})
        with self.assertRaisesRegex(ValueError, "RUNTIME_REQUIRED"):
            m.apply(type("Fork", (), {"url": "http://invalid"})())

    def test_reentrancy_requires_unique_seam(self):
        m = ReentrancyGuardSubstitute("0x" + "11" * 20, "0x6000", "0x12345678", {"match_count": 2})
        with self.assertRaisesRegex(ValueError, "SEAM_NOT_UNIQUE"):
            m.apply(type("Fork", (), {"url": "http://invalid"})())

    def test_arithmetic_requires_frozen_runtime(self):
        m = ArithmeticGuardInsert("0x" + "22" * 20, "0x12345678", "x <= bound", descriptor={"match_count": 1})
        with self.assertRaisesRegex(ValueError, "RUNTIME_REQUIRED"):
            m.apply(type("Fork", (), {"url": "http://invalid"})())


if __name__ == "__main__": unittest.main()

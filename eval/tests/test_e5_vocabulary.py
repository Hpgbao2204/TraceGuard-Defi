import unittest
from eval.e5.vocabulary import FalsificationOutcome, from_e4, to_e4


class TestVocabulary(unittest.TestCase):
    def test_e4_e5_supported_roundtrip(self):
        self.assertEqual(from_e4("NECESSITY_SUPPORTED"), FalsificationOutcome.SUPPORTED)
        self.assertEqual(to_e4(FalsificationOutcome.SUPPORTED), "NECESSITY_SUPPORTED")

    def test_unknown_is_fail_closed(self):
        self.assertEqual(from_e4("future-label"), FalsificationOutcome.NOT_TESTABLE)


if __name__ == "__main__": unittest.main()

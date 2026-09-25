import unittest

from eval.e5.label_crosswalk import _agreement, build_crosswalk, resolve_incident


class TestE5LabelCrosswalk(unittest.TestCase):
    def test_exact_hash_match(self):
        case = {"case_id": "defihacklabs-a-2025-01-01", "tx_hash": "0x" + "a" * 64}
        record = {"id": case["case_id"], "tx_hashes": [case["tx_hash"]]}
        found, confidence = resolve_incident(case, [record])
        self.assertIs(found, record)
        self.assertEqual(confidence, "EXACT")

    def test_agreement_does_not_duplicate_one_source(self):
        row = {"sources": {"one": {"claim": {"factor_labels": ["x"]}, "match_confidence": "EXACT"}, "two": {"claim": None}}}
        self.assertEqual(_agreement([row]), {})

    def test_missing_external_sources_are_not_claims(self):
        manifest = {"cases": [{"case_id": "defihacklabs-a-2025-01-01", "tx_hash": "0x" + "a" * 64}]}
        record = {"id": manifest["cases"][0]["case_id"], "tx_hashes": [manifest["cases"][0]["tx_hash"]], "gt_factors": ["f_auth"], "attack_type": "access", "notes": "manual claim"}
        out = build_crosswalk(manifest, [record])
        self.assertEqual(out["gate0"]["cases_with_at_least_two_sources"], 0)
        self.assertEqual(out["cases"][0]["sources"]["txray"]["match_confidence"], "MISSING")


if __name__ == "__main__":
    unittest.main()

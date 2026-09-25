from __future__ import annotations

import unittest

from eval.grouped_split_v2 import build_groups, split_rows


class GroupedSplitV2Tests(unittest.TestCase):
    def rows(self) -> list[dict]:
        return [
            {"tx_hash": "a1", "label": "attack", "block": 10, "incident_id": "i1"},
            {"tx_hash": "a2", "label": "attack", "block": 10, "incident_id": "i2"},
            {"tx_hash": "b1", "label": "benign", "block": 11, "incident_id": "i3"},
            {"tx_hash": "b2", "label": "benign", "block": 12, "incident_id": "i3"},
            {"tx_hash": "c1", "label": "benign", "block": 13, "incident_id": "i4"},
            {"tx_hash": "d1", "label": "benign", "block": 14, "incident_id": "i5"},
        ]

    def test_block_and_incident_relations_are_transitive(self) -> None:
        groups = build_groups(self.rows())
        self.assertEqual(groups["a1"], groups["a2"])
        self.assertEqual(groups["b1"], groups["b2"])
        self.assertNotEqual(groups["a1"], groups["b1"])

    def test_split_is_deterministic_and_disjoint(self) -> None:
        first = split_rows(self.rows(), seed=42)
        second = split_rows(self.rows(), seed=42)
        self.assertEqual(first.as_dict(), second.as_dict())
        values = [tx for partition in first.partitions.values() for tx in partition]
        self.assertEqual(len(values), len(set(values)))
        self.assertEqual(set(values), {row["tx_hash"] for row in self.rows()})
        for partition in first.partitions.values():
            partition_groups = {first.groups[tx] for tx in partition}
            for other in first.partitions.values():
                if partition is not other:
                    self.assertTrue(partition_groups.isdisjoint({first.groups[tx] for tx in other}))

    def test_manifest_reports_impossible_empty_partition(self) -> None:
        manifest = split_rows(self.rows()[:2])
        self.assertIsNotNone(manifest.infeasible_reason)


if __name__ == "__main__":
    unittest.main()

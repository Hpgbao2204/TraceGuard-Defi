from pathlib import Path

from eval.e1_grouped_robustness_v2 import _group_split
from eval.e1_train import build_dataset


def test_group_split_partitions_are_disjoint_and_class_complete():
    ds = build_dataset(Path("eval/results/e1_trace_cache.jsonl"))
    hashes = [row["tx_hash"] for row in ds["rows"]]
    fit, calibration, groups = _group_split(ds["rows"], hashes)
    assert not set(fit) & set(calibration)
    assert set(fit) | set(calibration) == set(hashes)
    assert {next(row for row in ds["rows"] if row["tx_hash"] == h)["label"] for h in fit} == {"attack", "benign"}
    assert {next(row for row in ds["rows"] if row["tx_hash"] == h)["label"] for h in calibration} == {"attack", "benign"}
    assert len(groups) == len(hashes)

"""Evaluate internal baseline proxies on the frozen grouped-v2 test set."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from core.artifacts import ArtifactStore
from eval.e1_baselines import BASELINE_SCORERS, BASELINES
from eval.e1_common import metrics_at_thresholds, select_fpr_thresholds
from eval.e1_train import build_dataset
from core.protocol import SCREENING_PROTOCOL_VERSION

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CACHE = ROOT / "eval/results/e1_trace_cache.jsonl"
DEFAULT_SPLIT = ROOT / "eval/results/runs/e1-grouped-v2-freeze-20260909-r2"
DEFAULT_RUNS = ROOT / "eval/results/runs"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(cache: Path, split_dir: Path, runs_dir: Path, run_id: str) -> Path:
    cache, split_dir = cache.resolve(), split_dir.resolve()
    metadata = json.loads((split_dir / "run_metadata.json").read_text())
    expected = metadata.get("inputs", {}).get("cache_sha256")
    if expected and _sha256(cache) != expected:
        raise ValueError("cache checksum does not match frozen split")
    split = json.loads((split_dir / "split_manifest.json").read_text())
    ds = build_dataset(cache)
    by_hash = {row["tx_hash"]: row for row in ds["rows"]}
    cal_h, test_h = split["partitions"]["calibration"], split["partitions"]["test"]
    y_cal = np.array([by_hash[h]["label"] == "attack" for h in cal_h], dtype=float)
    y_test = np.array([by_hash[h]["label"] == "attack" for h in test_h], dtype=float)
    store = ArtifactStore(runs_dir)
    store.create_run(run_id, {
        "experiment": "E1-screening-grouped-v2-baselines",
        "protocol_version": SCREENING_PROTOCOL_VERSION,
        "parent_split_run": metadata["run_id"],
        "inputs": {"cache_sha256": _sha256(cache), "split_sha256": _sha256(split_dir / "split_manifest.json")},
        "design": {"threshold_source": "calibration partition only", "scope": "internal diagnostic proxies"},
    })
    row_by_hash = {row["tx_hash"]: row["row"] for row in ds["rows"]}
    outputs = {}
    for name in BASELINES:
        scorer = BASELINE_SCORERS[name]
        cal_scores = np.array([scorer(row_by_hash[h]) for h in cal_h])
        test_scores = np.array([scorer(row_by_hash[h]) for h in test_h])
        thresholds = select_fpr_thresholds(y_cal, cal_scores, budgets=(0.001, 0.01))
        outputs[name] = {
            "thresholds": thresholds,
            "metrics": metrics_at_thresholds(y_test, test_scores, thresholds, budgets=(0.001, 0.01)),
        }
    store.write_json(run_id, "baseline_metrics.json", outputs)
    store.finalize(run_id)
    return runs_dir / run_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--split-dir", type=Path, default=DEFAULT_SPLIT)
    parser.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    print(json.dumps({"run_dir": str(run(args.cache, args.split_dir, args.runs_dir, args.run_id))}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Report view coverage and score performance by coverage strata."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import numpy as np

from core.artifacts import ArtifactStore
from eval.e1_common import metrics_at_thresholds
from eval.e1_train import build_dataset
from core.protocol import SCREENING_PROTOCOL_VERSION, SCREENING_VIEWS

ROOT = Path(__file__).resolve().parent.parent
PRIMARY_VIEWS = SCREENING_VIEWS


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(cache: Path, model_dir: Path, split_dir: Path, runs_dir: Path, run_id: str) -> Path:
    cache, model_dir, split_dir = cache.resolve(), model_dir.resolve(), split_dir.resolve()
    split_meta = json.loads((split_dir / "run_metadata.json").read_text())
    expected = split_meta.get("inputs", {}).get("cache_sha256")
    if expected and _sha256(cache) != expected:
        raise ValueError("cache checksum does not match frozen split")
    split = json.loads((split_dir / "split_manifest.json").read_text())
    metrics = json.loads((model_dir / "metrics.json").read_text())
    predictions = {row["tx_hash"]: row for row in json.loads((model_dir / "test_predictions.json").read_text())}
    ds = build_dataset(cache)
    by_hash = {row["tx_hash"]: row for row in ds["rows"]}
    test_hashes = split["partitions"]["test"]
    if set(predictions) != set(test_hashes):
        raise ValueError("model predictions do not match frozen test partition")
    patterns = Counter()
    strata = {}
    for h in test_hashes:
        scores = ds["scores"][h]
        pattern = tuple(view for view in PRIMARY_VIEWS if scores.get(view) is not None)
        key = "+".join(pattern) if pattern else "none"
        patterns[key] += 1
        strata.setdefault(key, []).append(h)
    outputs = {}
    threshold_map = {float(k): float(v) for k, v in metrics["thresholds"].items()}
    for key, hashes in sorted(strata.items()):
        y = np.array([by_hash[h]["label"] == "attack" for h in hashes], dtype=float)
        scores = np.array([predictions[h]["score"] for h in hashes], dtype=float)
        if len(set(y)) < 2:
            outputs[key] = {"n": len(hashes), "n_attack": int(y.sum()), "status": "insufficient_class"}
        else:
            outputs[key] = {"n": len(hashes), "n_attack": int(y.sum()), "status": "evaluated", "metrics": metrics_at_thresholds(y, scores, threshold_map, budgets=(0.001, 0.01))}
    covered = [h for h in test_hashes if all(by_hash[h]["row"] and ds["scores"][h].get(v) is not None for v in PRIMARY_VIEWS)]
    result = {"protocol_version": SCREENING_PROTOCOL_VERSION, "primary_views": list(PRIMARY_VIEWS), "coverage_patterns": patterns, "strata": outputs, "covered_only_n": len(covered), "covered_only_fraction": len(covered) / len(test_hashes)}
    store = ArtifactStore(runs_dir)
    store.create_run(run_id, {"experiment": "E1-screening-grouped-v2-missingness", "protocol_version": "screening-grouped-v2", "parent_model_run": model_dir.name, "parent_split_run": split_meta["run_id"], "inputs": {"cache_sha256": _sha256(cache), "model_sha256": _sha256(model_dir / "model.json"), "split_sha256": _sha256(split_dir / "split_manifest.json")}, "design": {"status": "diagnostic", "threshold_source": "parent calibration partition"}})
    store.write_json(run_id, "missingness.json", result)
    store.finalize(run_id)
    return runs_dir / run_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=ROOT / "eval/results/e1_trace_cache.jsonl")
    parser.add_argument("--model-dir", type=Path, default=ROOT / "eval/results/runs/e1-grouped-v2-fit-20260909-r3")
    parser.add_argument("--split-dir", type=Path, default=ROOT / "eval/results/runs/e1-grouped-v2-freeze-20260909-r2")
    parser.add_argument("--runs-dir", type=Path, default=ROOT / "eval/results/runs")
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    print(json.dumps({"run_dir": str(run(args.cache, args.model_dir, args.split_dir, args.runs_dir, args.run_id))}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

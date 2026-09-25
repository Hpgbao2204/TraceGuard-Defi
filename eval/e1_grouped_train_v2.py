"""Fit and evaluate the frozen screening-grouped-v2 split."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from core.artifacts import ArtifactStore
from core.fusion import calibrate_temperature, expected_calibration_error, fit_logistic_fusion

from .e1_common import metrics_at_thresholds, select_fpr_thresholds
from .e1_train import VIEWS, _view_matrix, build_dataset
from core.protocol import SCREENING_FEATURE_CONTRACT_VERSION, SCREENING_PROTOCOL_VERSION
from .run_manifest import git_revision

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CACHE = ROOT / "eval" / "results" / "e1_trace_cache.jsonl"
DEFAULT_SPLIT = ROOT / "eval" / "results" / "runs" / "e1-grouped-v2-freeze-20260909-r1"
DEFAULT_RUNS = ROOT / "eval" / "results" / "runs"


def train(split_dir: Path, runs_dir: Path, run_id: str, cache: Path) -> Path:
    split_dir, cache = split_dir.resolve(), cache.resolve()
    metadata = json.loads((split_dir / "run_metadata.json").read_text(encoding="utf-8"))
    split = json.loads((split_dir / "split_manifest.json").read_text(encoding="utf-8"))
    if split.get("protocol_version") != SCREENING_PROTOCOL_VERSION:
        raise ValueError("split manifest is not screening-grouped-v2")
    if tuple(split.get("views", ())) != tuple(VIEWS):
        raise ValueError("split manifest feature contract does not match training views")
    ds = build_dataset(cache)
    expected_cache_sha = metadata.get("inputs", {}).get("cache_sha256")
    if expected_cache_sha and _sha256(cache) != expected_cache_sha:
        raise ValueError("cache checksum does not match frozen split input")
    by_hash = {row["tx_hash"]: row for row in ds["rows"]}
    parts = split["partitions"]
    if set().union(*(set(values) for values in parts.values())) != set(by_hash):
        raise ValueError("split rows do not match cache rows")
    store = ArtifactStore(runs_dir)
    run_dir = store.create_run(run_id, {
        "experiment": "E1-screening-grouped-v2",
        "protocol_version": SCREENING_PROTOCOL_VERSION,
        "feature_contract_version": SCREENING_FEATURE_CONTRACT_VERSION,
        "code_provenance": git_revision(ROOT),
        "parent_split_run": metadata["run_id"],
        "inputs": {
            "cache": str(cache.relative_to(ROOT)),
            "cache_sha256": _sha256(cache),
            "split_manifest": str((split_dir / "split_manifest.json").relative_to(ROOT)),
        },
        "model": {"family": "logistic-fusion", "views": list(VIEWS), "seed": split["seed"]},
        "calibration": {"method": "temperature-scaling", "source": "calibration partition only"},
        "thresholds": {"budgets": [0.001, 0.01], "source": "calibration partition only"},
    })
    fit_h, cal_h, test_h = (parts[name] for name in ("fit", "calibration", "test"))
    y = {h: float(by_hash[h]["label"] == "attack") for h in by_hash}
    fit_x, fit_y = _matrix(ds, fit_h, y)
    cal_x, cal_y = _matrix(ds, cal_h, y)
    test_x, test_y = _matrix(ds, test_h, y)
    if len(set(fit_y)) < 2 or len(set(cal_y)) < 2 or len(set(test_y)) < 2:
        raise ValueError("fit, calibration and test partitions must contain both labels")
    model = fit_logistic_fusion(fit_x, fit_y, view_names=VIEWS, seed=split["seed"])
    calibrated = calibrate_temperature(model, cal_x, cal_y)
    cal_scores = calibrated.predict(cal_x)
    thresholds = select_fpr_thresholds(cal_y, cal_scores, budgets=(0.001, 0.01))
    test_scores = calibrated.predict(test_x)
    metrics = metrics_at_thresholds(test_y, test_scores, thresholds, budgets=(0.001, 0.01))
    model_payload = calibrated.to_dict()
    model_payload["protocol_version"] = SCREENING_PROTOCOL_VERSION
    model_payload["feature_contract_version"] = SCREENING_FEATURE_CONTRACT_VERSION
    model_payload["calibration_partition_count"] = len(cal_h)
    model_payload["calibration_ece"] = expected_calibration_error(cal_scores, cal_y)
    store.write_json(run_id, "model.json", model_payload)
    store.write_json(run_id, "metrics.json", {
        "protocol_version": SCREENING_PROTOCOL_VERSION,
        "feature_contract_version": SCREENING_FEATURE_CONTRACT_VERSION,
        "partition_counts": {name: len(parts[name]) for name in parts},
        "partition_labels": {
            name: {"attack": sum(y[h] == 1 for h in parts[name]),
                   "benign": sum(y[h] == 0 for h in parts[name])}
            for name in parts
        },
        "thresholds": thresholds,
        "metrics": metrics,
    })
    predictions = [{"tx_hash": h, "label": int(y[h]), "score": float(score)}
                   for h, score in zip(test_h, test_scores)]
    store.write_json(run_id, "test_predictions.json", predictions)
    store.finalize(run_id)
    return run_dir


def _matrix(ds: dict, hashes: list[str] | tuple[str, ...], labels: dict[str, float]) -> tuple[np.ndarray, np.ndarray]:
    return _view_matrix(ds, list(hashes)), np.array([labels[h] for h in hashes], dtype=float)


def _sha256(path: Path) -> str:
    import hashlib
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split-dir", type=Path, default=DEFAULT_SPLIT)
    parser.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    path = train(args.split_dir, args.runs_dir, args.run_id, args.cache)
    print(json.dumps({"run_dir": str(path), "status": "model-evaluated"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

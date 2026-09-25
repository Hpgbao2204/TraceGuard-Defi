"""Run frozen-protocol grouped-v2 split sensitivity and cluster bootstrap."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from core.artifacts import ArtifactStore
from core.fusion import calibrate_temperature, fit_logistic_fusion
from eval.e1_common import metrics_at_thresholds, select_fpr_thresholds
from eval.e1_train import VIEWS, _view_matrix, build_dataset
from eval.grouped_split_v2 import build_groups, split_rows
from core.protocol import SCREENING_PROTOCOL_VERSION, SCREENING_VIEWS

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CACHE = ROOT / "eval/results/e1_trace_cache.jsonl"
DEFAULT_RUNS = ROOT / "eval/results/runs"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fit(
    ds: dict, manifest: dict, seed: int
) -> tuple[dict, dict, np.ndarray, np.ndarray, list[str]]:
    by_hash = {row["tx_hash"]: row for row in ds["rows"]}
    parts = split_rows(ds["rows"], seed=seed).as_dict()["partitions"]
    labels = {h: float(by_hash[h]["label"] == "attack") for h in by_hash}

    def matrix(name: str) -> tuple[np.ndarray, np.ndarray]:
        hs = parts[name]
        return _view_matrix(ds, hs), np.array([labels[h] for h in hs], dtype=float)

    x_fit, y_fit = matrix("fit")
    x_cal, y_cal = matrix("calibration")
    x_test, y_test = matrix("test")
    model = calibrate_temperature(
        fit_logistic_fusion(x_fit, y_fit, view_names=SCREENING_VIEWS, seed=seed), x_cal, y_cal
    )
    thresholds = select_fpr_thresholds(
        y_cal, model.predict(x_cal), budgets=(0.001, 0.01)
    )
    scores = model.predict(x_test)
    return (
        metrics_at_thresholds(y_test, scores, thresholds, budgets=(0.001, 0.01)),
        thresholds,
        y_test,
        scores,
        parts["test"],
    )


def run(
    cache: Path,
    runs_dir: Path,
    run_id: str,
    start_seed: int = 42,
    count: int = 30,
    bootstrap: int = 1000,
) -> Path:
    ds = build_dataset(cache)
    store = ArtifactStore(runs_dir)
    run_dir = store.create_run(
        run_id,
        {
            "experiment": "E1-screening-grouped-v2-sensitivity",
            "protocol_version": SCREENING_PROTOCOL_VERSION,
            "seed_range": [start_seed, start_seed + count - 1],
            "bootstrap_replicates": bootstrap,
            "inputs": {
                "cache": str(cache),
                "cache_sha256": _sha256(cache),
                "row_count": len(ds["rows"]),
            },
        },
    )
    rows = []
    reference = None
    for seed in range(start_seed, start_seed + count):
        metrics, thresholds, y, scores, test_hashes = _fit(ds, {}, seed)
        row = {
            "seed": seed,
            "thresholds": thresholds,
            "metrics": metrics,
            "n_test": len(test_hashes),
            "n_attack": int(y.sum()),
            "n_benign": int((y == 0).sum()),
        }
        rows.append(row)
        if seed == 42:
            reference = (y, scores, test_hashes)
    if reference is None:
        raise ValueError("seed 42 must be included for reference bootstrap")
    y, scores, hashes = reference
    all_groups = build_groups(ds["rows"])
    groups = np.array([all_groups[h] for h in hashes], dtype=object)
    rng = np.random.default_rng(20260909)
    auc_values = []
    clusters = sorted({str(group) for group in groups})
    cluster_indices = {
        cluster: np.flatnonzero(groups == cluster).tolist() for cluster in clusters
    }
    thresholds = rows[0]["thresholds"]
    for _ in range(bootstrap):
        sampled_clusters = rng.choice(clusters, len(clusters), replace=True)
        sampled = np.concatenate(
            [cluster_indices[str(cluster)] for cluster in sampled_clusters]
        )
        if len({int(value) for value in y[sampled]}) < 2:
            continue
        auc_values.append(
            float(
                metrics_at_thresholds(
                    y[sampled], scores[sampled], thresholds, budgets=(0.001, 0.01)
                )["auc_pr"]
            )
        )
    summary = {
        "protocol_version": SCREENING_PROTOCOL_VERSION,
        "runs": rows,
        "n_runs": len(rows),
        "seed_range": [start_seed, start_seed + count - 1],
        "bootstrap": {
            "n_requested": bootstrap,
            "n": len(auc_values),
            "seed": 20260909,
            "n_test_clusters": len(clusters),
            "cluster_definition": "connected groups from grouped split relation keys",
            "auc_pr": {
                "low": float(np.percentile(auc_values, 2.5)),
                "median": float(np.percentile(auc_values, 50)),
                "high": float(np.percentile(auc_values, 97.5)),
            },
        },
    }
    store.write_json(run_id, "sensitivity.json", summary)
    store.finalize(run_id)
    return run_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--count", type=int, default=30)
    parser.add_argument("--bootstrap", type=int, default=1000)
    args = parser.parse_args(argv)
    print(
        json.dumps(
            {
                "run_dir": str(
                    run(
                        args.cache,
                        args.runs_dir,
                        args.run_id,
                        count=args.count,
                        bootstrap=args.bootstrap,
                    )
                )
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

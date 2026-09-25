"""Paired E3 evaluation using one frozen grouped-v2 model and threshold."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from core.artifacts import ArtifactStore
from core.protocol import SCREENING_PROTOCOL_VERSION
from eval.e1_common import metrics_at_thresholds
from eval.e1_robustness import _is_near_negative
from eval.e1_train import _view_matrix, build_dataset

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL_RUN = ROOT / "eval/results/runs/e1-grouped-v2-fit-20260909-r2"
DEFAULT_SPLIT_RUN = ROOT / "eval/results/runs/e1-grouped-v2-freeze-20260909-r1"
DEFAULT_CACHE = ROOT / "eval/results/e1_trace_cache.jsonl"
DEFAULT_RUNS = ROOT / "eval/results/runs"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _score_hashes(ds: dict, hashes: list[str], model: dict) -> np.ndarray:
    """Return scores in exactly the order supplied by ``hashes``."""
    matrix = _view_matrix(ds, hashes)
    weights = np.array([model["weights"][name] for name in model["view_names"]])
    return 1.0 / (1.0 + np.exp(-(float(model["offset"]) + matrix @ weights)))


def evaluate(model_run: Path, split_run: Path, cache: Path, runs_dir: Path, run_id: str) -> Path:
    model_run, split_run, cache = model_run.resolve(), split_run.resolve(), cache.resolve()
    model = json.loads((model_run / "model.json").read_text(encoding="utf-8"))
    metrics = json.loads((model_run / "metrics.json").read_text(encoding="utf-8"))
    split = json.loads((split_run / "split_manifest.json").read_text(encoding="utf-8"))
    seed = int(split.get("seed", 42))
    ds = build_dataset(cache)
    model_metadata = json.loads((model_run / "run_metadata.json").read_text(encoding="utf-8"))
    split_metadata = json.loads((split_run / "run_metadata.json").read_text(encoding="utf-8"))
    for metadata in (model_metadata, split_metadata):
        expected = metadata.get("inputs", {}).get("cache_sha256")
        if expected and _sha256(cache) != expected:
            raise ValueError("cache checksum does not match parent run input")
    by_hash = {row["tx_hash"]: row for row in ds["rows"]}
    test_hashes = split["partitions"]["test"]
    prediction_rows = json.loads((model_run / "test_predictions.json").read_text())
    prediction_by_hash = {row["tx_hash"]: row for row in prediction_rows}
    if set(prediction_by_hash) != set(test_hashes):
        raise ValueError("model predictions do not match frozen test partition")
    prediction_order = [row["tx_hash"] for row in prediction_rows]
    recalculated = _score_hashes(ds, prediction_order, model)
    recorded = np.array([float(row["score"]) for row in prediction_rows])
    if not np.allclose(recalculated, recorded, rtol=0.0, atol=1e-12):
        raise ValueError("stored test predictions do not match parent model")
    near = {h for h in test_hashes if by_hash[h]["label"] == "benign" and _is_near_negative(by_hash[h]["row"])}
    ordinary = {h for h in test_hashes if by_hash[h]["label"] == "benign" and h not in near}
    positives = {h for h in test_hashes if by_hash[h]["label"] == "attack"}
    threshold_map = {float(key): float(value) for key, value in metrics["thresholds"].items()}
    store = ArtifactStore(runs_dir)
    run_dir = store.create_run(run_id, {
        "experiment": "E3-screening-grouped-v2-paired",
        "protocol_version": SCREENING_PROTOCOL_VERSION,
        "parent_model_run": model_run.name,
        "parent_split_run": split_run.name,
        "inputs": {"cache_sha256": _sha256(cache), "model_sha256": _sha256(model_run / "model.json"), "split_sha256": _sha256(split_run / "split_manifest.json")},
        "design": {"same_model": True, "same_thresholds": True, "same_positive_test_cohort": True, "near_definition": "known flash/oracle/swap selector OR >=10 calls OR >=5 logs"},
    })
    def score(hashes: list[str]) -> np.ndarray:
        """Score hashes in caller order; labels must use the same order."""
        return _score_hashes(ds, hashes, model)
    outputs = {}
    for name, negatives in (("ordinary", ordinary), ("near_negative", near)):
        cohort = sorted(positives | negatives)
        y = np.array([1 if h in positives else 0 for h in cohort], dtype=float)
        scores = score(cohort)
        if len(scores) != len(y):
            raise AssertionError("score/label alignment mismatch")
        outputs[name] = {"hashes": cohort, "n_positive": len(positives), "n_negative": len(negatives), "metrics": metrics_at_thresholds(y, scores, threshold_map, budgets=(0.001, 0.01))}
    equal_n = min(len(near), len(ordinary))
    equal_outputs = {}
    if equal_n:
        for name, negatives in (("near_negative_equal_size", near),
                                ("ordinary_equal_size", ordinary)):
            selected = sorted(
                negatives,
                key=lambda h: hashlib.sha256(
                    f"{seed}:{name}:{h}".encode()).hexdigest(),
            )[:equal_n]
            cohort = sorted(positives | set(selected))
            y = np.array([1 if h in positives else 0 for h in cohort], dtype=float)
            equal_outputs[name] = {
                "hashes": cohort,
                "n_positive": len(positives),
                "n_negative": len(selected),
                "metrics": metrics_at_thresholds(
                    y, score(cohort), threshold_map, budgets=(0.001, 0.01)),
            }
    else:
        equal_outputs = {"status": "N/A", "reason": "one negative cohort is empty"}
    for threshold in threshold_map:
        ordinary_tp = outputs["ordinary"]["metrics"][threshold]["tp"]
        near_tp = outputs["near_negative"]["metrics"][threshold]["tp"]
        if ordinary_tp != near_tp:
            raise AssertionError("positive cohort score changed between E3 cohorts")
    test_metrics = metrics_at_thresholds(
        np.array([1 if h in positives else 0 for h in sorted(test_hashes)], dtype=float),
        score(sorted(test_hashes)), threshold_map, budgets=(0.001, 0.01),
    )
    for threshold in threshold_map:
        expected_fp = test_metrics[threshold]["fp"]
        observed_fp = (
            outputs["ordinary"]["metrics"][threshold]["fp"]
            + outputs["near_negative"]["metrics"][threshold]["fp"]
        )
        if expected_fp != observed_fp:
            raise AssertionError("E3 cohort false positives do not partition test set")
    store.write_json(run_id, "validation.json", {
        "score_label_alignment": "ordered_hashes",
        "positive_cohort_consistent": True,
        "negative_cohorts_partition_test": True,
        "retired_prior_run_reason": "set-order score/label mismatch",
    })
    store.write_json(run_id, "paired_metrics.json", outputs)
    store.write_json(run_id, "equal_size_metrics.json", equal_outputs)
    store.write_json(run_id, "cohort_manifest.json", {
        "positive_test": sorted(positives),
        "ordinary_negative_test": sorted(ordinary),
        "near_negative_test": sorted(near),
        "equal_size": equal_outputs,
    })
    store.finalize(run_id)
    return run_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-run", type=Path, default=DEFAULT_MODEL_RUN)
    parser.add_argument("--split-run", type=Path, default=DEFAULT_SPLIT_RUN)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    path = evaluate(args.model_run, args.split_run, args.cache, args.runs_dir, args.run_id)
    print(json.dumps({"run_dir": str(path), "status": "paired-evaluated"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

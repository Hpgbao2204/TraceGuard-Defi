"""Group-safe temporal and held-family screening diagnostics."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from core.artifacts import ArtifactStore
from core.fusion import calibrate_temperature, fit_logistic_fusion
from eval.e1_common import metrics_at_thresholds, select_fpr_thresholds
from eval.e1_train import _view_matrix, build_dataset
from eval.grouped_split_v2 import build_groups
from core.protocol import SCREENING_PROTOCOL_VERSION, SCREENING_VIEWS


def _screening_matrix(ds: dict, hashes: list[str]) -> np.ndarray:
    """Select the canonical Stage 1 views from cache rows."""
    return _view_matrix(ds, hashes)


def _fit(ds: dict, fit_hashes: list[str], cal_hashes: list[str], seed: int):
    by_hash = {row["tx_hash"]: row for row in ds["rows"]}
    def labels(hashes: list[str]) -> np.ndarray:
        return np.array([by_hash[h]["label"] == "attack" for h in hashes], dtype=float)
    fit_x, fit_y = _screening_matrix(ds, fit_hashes), labels(fit_hashes)
    cal_x, cal_y = _screening_matrix(ds, cal_hashes), labels(cal_hashes)
    if len(set(fit_y)) < 2 or len(set(cal_y)) < 2:
        return None, "fit-or-calibration-missing-class"
    model = calibrate_temperature(
        fit_logistic_fusion(fit_x, fit_y, view_names=SCREENING_VIEWS, seed=seed),
        cal_x, cal_y)
    return (model, select_fpr_thresholds(cal_y, model.predict(cal_x),
                                         (0.001, 0.01))), None


def _group_split(rows: list[dict], hashes: list[str], *, seed: int = 42):
    groups = build_groups([row for row in rows if row["tx_hash"] in set(hashes)])
    members: dict[str, list[str]] = {}
    for tx_hash, group in groups.items():
        members.setdefault(group, []).append(tx_hash)
    ordered = sorted(members, key=lambda g: (min(int(next(r for r in rows if r["tx_hash"] == h).get("block") or 0) for h in members[g]), g))
    labels_by_group = {
        group: any(next(r for r in rows if r["tx_hash"] == h)["label"] == "attack"
                   for h in members[group])
        for group in ordered
    }
    cal_groups = set(ordered[::5])
    # Reserve one group of each class for calibration while preserving at
    # least one group of each class in fit.
    for wanted in (True, False):
        candidate = next((g for g in ordered if labels_by_group[g] is wanted), None)
        if candidate is not None:
            cal_groups.add(candidate)
    cal = sorted(h for g in cal_groups for h in members[g])
    fit = sorted(h for g in ordered if g not in cal_groups for h in members[g])
    fit_labels = {next(r for r in rows if r["tx_hash"] == h)["label"] for h in fit}
    if len(fit_labels) < 2:
        for group in ordered:
            if group in cal_groups and labels_by_group[group]:
                cal_groups.remove(group)
                break
        cal = sorted(h for g in cal_groups for h in members[g])
        fit = sorted(h for g in ordered if g not in cal_groups for h in members[g])
    return fit, cal, groups


def evaluate(cache: Path, runs_dir: Path, run_id: str, seed: int = 42) -> Path:
    ds = build_dataset(cache)
    rows = ds["rows"]
    by_hash = {row["tx_hash"]: row for row in rows}
    groups = build_groups(rows)
    attack_rows = [row for row in rows if row["label"] == "attack" and row.get("block") is not None]
    cutoff = sorted(int(row["block"]) for row in attack_rows)[max(0, int(.8 * len(attack_rows)) - 1)]
    store = ArtifactStore(runs_dir)
    store.create_run(run_id, {
        "experiment": "E1-E2-grouped-robustness-v2",
        "protocol_version": SCREENING_PROTOCOL_VERSION,
        "inputs": {
            "cache": str(cache),
            "cache_sha256": hashlib.sha256(cache.read_bytes()).hexdigest(),
            "row_count": len(rows),
            "tx_hashes_sha256": hashlib.sha256(
                "\n".join(sorted(row["tx_hash"] for row in rows)).encode()
            ).hexdigest(),
        },
        "design": {
            "group_safe": True,
            "calibration_by_group": True,
            "cutoff_frozen": True,
            "seed": seed,
            "temporal_attack_quantile": 0.8,
            "calibration_group_stride": 5,
        },
    })
    store.write_json(run_id, "input_manifest.json", {
        "cache": str(cache),
        "cache_sha256": hashlib.sha256(cache.read_bytes()).hexdigest(),
        "row_count": len(rows),
        "hash_to_group": build_groups(rows),
        "cutoff_block": cutoff,
    })
    group_blocks: dict[str, list[int]] = {}
    for h, group in groups.items():
        if by_hash[h].get("block") is not None:
            group_blocks.setdefault(group, []).append(int(by_hash[h]["block"]))
    temporal_train = sorted(h for h, g in groups.items() if max(group_blocks.get(g, [0])) <= cutoff)
    temporal_test = sorted(h for h, g in groups.items() if min(group_blocks.get(g, [0])) > cutoff)
    train_fit, train_cal, _ = _group_split(rows, temporal_train, seed=seed)
    if (set(train_fit) & set(train_cal) or set(train_fit) & set(temporal_test)
            or set(train_cal) & set(temporal_test)):
        raise AssertionError("temporal group split overlaps partitions")
    fold_manifest = {
        "temporal": {"fit": train_fit, "calibration": train_cal,
                     "test": temporal_test},
    }
    fold_specs = [("E1-temporal-grouped", train_fit, train_cal, temporal_test,
                   {"cutoff_block": cutoff, "quarantined_groups": sum(
                       min(group_blocks.get(g, [0])) <= cutoff < max(
                           group_blocks.get(g, [0]))
                       for g in set(groups.values()))})]
    benign_groups = sorted(
        {groups[h] for h, r in by_hash.items() if r["label"] == "benign"},
        key=lambda group: f"{seed}:{group}",
    )
    benign_test_groups = set(benign_groups[:max(1, len(benign_groups) // 5)])
    benign = sorted(h for h, r in by_hash.items()
                    if r["label"] == "benign" and groups[h] in benign_test_groups)
    for family in sorted({r["attack_type"] for r in rows if r["label"] == "attack"}):
        held_groups = {groups[r["tx_hash"]] for r in rows
                       if r["label"] == "attack" and r["attack_type"] == family}
        held = sorted(h for h, g in groups.items() if g in held_groups)
        test_b_groups = {groups[h] for h in benign}
        pool = sorted(h for h, g in groups.items()
                      if g not in held_groups and g not in test_b_groups)
        fit_h, cal_h, _ = _group_split(rows, pool, seed=seed)
        test = sorted(set(held + benign))
        if set(fit_h) & (set(cal_h) | set(test)) or set(cal_h) & set(test):
            raise AssertionError("held-family group split overlaps partitions")
        fold_name = f"held-family:{family}"
        fold_manifest[fold_name] = {
            "fit": fit_h, "calibration": cal_h, "test": test,
            "held_groups": sorted(held_groups),
            "benign_test_groups": sorted(test_b_groups),
        }
        fold_specs.append(("E2-held-family-grouped", fit_h, cal_h, test,
                           {"held_family": family,
                            "held_groups": len(held_groups),
                            "family_primary": sum(
                                r["label"] == "attack" and
                                r["attack_type"] == family for r in rows) >= 3}))
    # Freeze every partition before fitting any model. The manifest is the
    # authoritative input for the scoring pass below.
    store.write_json(run_id, "group_manifest.json", {
        "hash_to_group": groups, "folds": fold_manifest,
        "temporal_test": temporal_test,
    })
    results = []
    prediction_records = []
    def score_case(name: str, fit_h: list[str], cal_h: list[str], test_h: list[str], meta: dict):
        fitted, reason = _fit(ds, fit_h, cal_h, seed)
        if reason:
            results.append({"experiment": name, "status": "N/A", "reason": reason, **meta})
            return
        model, thresholds = fitted
        y = np.array([by_hash[h]["label"] == "attack" for h in test_h], dtype=float)
        scores = model.predict(_screening_matrix(ds, test_h))
        metrics = metrics_at_thresholds(y, scores, thresholds, (0.001, 0.01))
        prediction_records.append({
            "experiment": name,
            "fit_hashes": fit_h,
            "calibration_hashes": cal_h,
            "test_hashes": test_h,
            "labels": y.astype(int).tolist(),
            "scores": scores.astype(float).tolist(),
            "thresholds": {str(k): float(v) for k, v in thresholds.items()},
            "model": model.to_dict(),
        })
        results.append({"experiment": name, "status": "evaluated", "n_fit": len(fit_h), "n_calibration": len(cal_h), "n_test": len(test_h), "metrics": metrics, **meta})
    for name, fit_h, cal_h, test_h, meta in fold_specs:
        score_case(name, fit_h, cal_h, test_h, meta)
    store.write_json(run_id, "grouped_robustness.json", {"results": results, "group_count": len(set(groups.values())), "cutoff_block": cutoff})
    store.write_json(run_id, "predictions.json", prediction_records)
    store.finalize(run_id)
    return runs_dir / run_id


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--runs-dir", type=Path, default=Path("eval/results/runs"))
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    print(json.dumps({"run_dir": str(evaluate(args.cache, args.runs_dir, args.run_id))}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Stage 1 checks requested in review, on the frozen block-grouped test set.

    python -m eval.revision.stage1_checks --out .cache/revision/stage1_checks.json

1. Paired stratified bootstrap of the AUPRC difference between the fused screener and BlockScan
   (eval.revision.blockscan) and each internal proxy baseline: both scorers are evaluated on the same
   resampled test transactions, so the interval is for the difference, not two overlapping intervals.
2. Temporal confounding: exploits date from 2024-2026 while background anchors span 2021-2026. The fused
   scores are re-evaluated with background restricted to blocks from 2024 on, so both classes come from
   the same period.
3. Cohort prevalence: the attack share of the test set with ordinary background only and with
   near-negatives only, the chance level of AUPRC for each cohort.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from eval.e1_baselines import BASELINE_SCORERS, BASELINES
from eval.e1_common import average_precision
from eval.e1_train import build_dataset
from eval.revision.stage1 import CACHE, COHORTS, ROOT, SPLIT, bootstrap_auprc, fit_eval

BLOCKSCAN = ROOT / ".cache" / "revision" / "blockscan"
FIRST_2024_BLOCK = 18_908_895  # first block of 2024-01-01 UTC


def paired_bootstrap(y, a, b, n=2000, seed=7) -> dict:
    rng = np.random.default_rng(seed)
    pos, neg = np.flatnonzero(y == 1), np.flatnonzero(y == 0)
    diffs = []
    for _ in range(n):
        idx = np.concatenate([rng.choice(pos, len(pos)), rng.choice(neg, len(neg))])
        diffs.append(average_precision(y[idx], a[idx]) - average_precision(y[idx], b[idx]))
    diffs = np.asarray(diffs)
    return {"diff": float(average_precision(y, a) - average_precision(y, b)),
            "ci95": [float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))],
            "frac_not_positive": float(np.mean(diffs <= 0))}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / ".cache" / "revision" / "stage1_checks.json")
    args = ap.parse_args()
    ds = build_dataset(CACHE)
    by_hash = {r["tx_hash"]: r for r in ds["rows"]}
    part = json.loads(SPLIT.read_text(encoding="utf-8"))["partitions"]
    fit_h, cal_h, test_h = list(part["fit"]), list(part["calibration"]), list(part["test"])
    _, _, s, y, _ = fit_eval(ds, by_hash, fit_h, cal_h, test_h)
    out: dict = {"fusion_auprc": average_precision(y, s)}

    order = json.loads((BLOCKSCAN / "tx_hashes.json").read_text(encoding="utf-8"))
    raw = json.loads((BLOCKSCAN / "scores.json").read_text(encoding="utf-8"))["scores"]
    bs = dict(zip(order, (float(r["score"]) for r in raw)))
    s_bs = np.array([bs[h] for h in test_h])
    out["vs_blockscan"] = paired_bootstrap(y, s, s_bs)
    out["vs_proxies"] = {}
    for name in BASELINES:
        f = BASELINE_SCORERS[name]
        out["vs_proxies"][name] = paired_bootstrap(y, s, np.array([f(by_hash[h]["row"]) for h in test_h]))

    recent = np.array([by_hash[h]["label"] == "attack" or by_hash[h]["block"] >= FIRST_2024_BLOCK for h in test_h])
    out["temporal"] = {"n_pos": int(y[recent].sum()), "n_neg_recent": int((y[recent] == 0).sum()),
                       "n_neg_all": int((y == 0).sum()),
                       "auprc_recent_background": average_precision(y[recent], s[recent]),
                       "auprc_recent_ci95": bootstrap_auprc(y[recent], s[recent]),
                       "blockscan_auprc_recent": average_precision(y[recent], s_bs[recent])}

    cohorts = json.loads(COHORTS.read_text(encoding="utf-8"))
    n_pos = len(cohorts["positive_test"])
    out["prevalence"] = {k: n_pos / (n_pos + len(cohorts[key])) for k, key in
                         (("ordinary", "ordinary_negative_test"), ("near_negative", "near_negative_test"),
                          ("all", None)) if key} | {"all": float(y.mean())}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

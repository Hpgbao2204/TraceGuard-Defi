"""Stage 1 threshold rules under block grouping (review item: the 1% budget on test).

    python -m eval.revision.threshold --out .cache/revision/threshold.json

The frozen rule picks tau on the pooled calibration partition. Under the block-grouped split the
calibration partition holds only a few background blocks, and near-negatives score differently from
block to block, so the pooled rule underestimates the FPR of unseen blocks. For each of the 50 seeds of
the grouped partitioner (same model as eval.revision.stage1, fit on the fit partition) this script
compares, on the untouched test partition:

  pooled        the frozen rule: highest recall with pooled calibration FPR <= alpha;
  cohort        the same rule with calibration negatives reweighted so that the near-negative share
                equals the share in all non-test background (near-negative is a label-free predicate);
  block_conf    block-level split conformal: every calibration background block is one exchangeable
                unit; tau is the largest per-block (1 - alpha) negative-score quantile, so a new block
                exceeds alpha with probability at most 1/(k+1) for k calibration blocks;
  crossfit      grouped 5-fold cross-fitting over fit+calibration: out-of-fold negative scores from
                models that never saw the block, each block weighted equally, tau at the (1 - alpha)
                quantile of that block mixture; the test model is unchanged.

It also reports the calibration-to-test FPR gap of the frozen rule and the implied alert volume per
mainnet block (background transactions per block x realized FPR).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from core.protocol import SCREENING_VIEWS
from eval.e1_common import metrics_at_thresholds
from eval.e1_robustness import _is_near_negative
from eval.e1_train import build_dataset
from eval.grouped_split_v2 import build_groups, split_rows
from eval.revision.stage1 import (
    BUDGET,
    CACHE,
    ROOT,
    SPLIT,
    _hash_fold,
    _labels,
    _matrix,
    fit_eval,
)

RULES = ("pooled", "cohort", "block_conf", "crossfit")


def weighted_threshold(y, s, w, alpha: float) -> float:
    """Lowest positive score whose weighted negative FPR stays within alpha (inf if none)."""
    y, s, w = np.asarray(y), np.asarray(s), np.asarray(w, dtype=float)
    neg_w = w[y == 0].sum()
    best, best_tp = float("inf"), 0
    for t in np.unique(s[y == 1])[::-1]:
        fpr = w[(y == 0) & (s >= t)].sum() / neg_w
        tp = int(((y == 1) & (s >= t)).sum())
        if fpr <= alpha + 1e-12 and tp > best_tp:
            best, best_tp = float(t), tp
    return best


def block_quantile(neg_scores: np.ndarray, alpha: float) -> float:
    """Smallest threshold whose FPR on one block's negatives is within alpha."""
    s = np.sort(neg_scores)[::-1]
    allowed = int(np.floor(alpha * len(s) + 1e-12))
    # scores strictly above the (allowed+1)-th largest are the only ones that may be flagged
    return float(np.nextafter(s[allowed], np.inf)) if allowed < len(s) else float("-inf")


def mixture_quantile(neg_by_block: dict, alpha: float) -> float:
    """Threshold whose block-averaged FPR is within alpha (each block weighted equally)."""
    cands = np.unique(np.concatenate(list(neg_by_block.values())))
    for t in cands:  # ascending: first t meeting the budget
        t_up = np.nextafter(t, np.inf)
        fpr = np.mean([np.mean(v >= t_up) for v in neg_by_block.values()])
        if fpr <= alpha + 1e-12:
            return float(t_up)
    return float("inf")


def evaluate_split(ds, by_hash, near, groups, fit_h, cal_h, test_h, seed: int) -> dict:
    """Fit on fit_h, select tau with every rule, and evaluate each on the untouched test_h."""
    model, tau0, s_test, y_test, _ = fit_eval(ds, by_hash, fit_h, cal_h, test_h, seed=seed)
    s_cal = model.predict(_matrix(ds, cal_h, SCREENING_VIEWS))
    y_cal = _labels(by_hash, cal_h)
    taus = {"pooled": tau0}

    # cohort-matched: reweight calibration negatives to the non-test near-negative share
    nontest_bg = [h for h in fit_h + cal_h if by_hash[h]["label"] != "attack"]
    pi = np.mean([h in near for h in nontest_bg])
    cal_near = np.array([h in near for h in cal_h])
    pi_cal = cal_near[y_cal == 0].mean()
    w = np.where(y_cal == 1, 1.0, np.where(cal_near, pi / pi_cal, (1 - pi) / (1 - pi_cal)))
    taus["cohort"] = weighted_threshold(y_cal, s_cal, w, BUDGET)

    # block-level split conformal on the calibration background blocks
    blocks: dict = {}
    for h, sc, yy in zip(cal_h, s_cal, y_cal):
        if yy == 0:
            blocks.setdefault(by_hash[h]["block"], []).append(sc)
    taus["block_conf"] = max(block_quantile(np.array(v), BUDGET) for v in blocks.values())

    # grouped 5-fold cross-fitting over fit+calibration (connected groups of the partitioner, so no
    # block or incident spans folds), block-equal mixture quantile
    train_h = fit_h + cal_h
    oof: dict = {}
    for f in range(5):
        te = [h for h in train_h if _hash_fold(f"{seed}:{groups[h]}", 5) == f]
        tr = [h for h in train_h if _hash_fold(f"{seed}:{groups[h]}", 5) != f]
        ca = [h for h in tr if _hash_fold("cal:" + groups[h], 5) == 0]
        fi = [h for h in tr if _hash_fold("cal:" + groups[h], 5) != 0]
        _, _, s_f, y_f, _ = fit_eval(ds, by_hash, fi, ca, te, seed=seed)
        for h, sc, yy in zip(te, s_f, y_f):
            if yy == 0:
                oof.setdefault(by_hash[h]["block"], []).append(sc)
    taus["crossfit"] = mixture_quantile({b: np.array(v) for b, v in oof.items()}, BUDGET)

    neg = y_test == 0
    t_near = np.array([h in near for h in test_h])
    rec = {"seed": seed, "n_cal_blocks": len(blocks), "n_crossfit_blocks": len(oof),
           "cal_fpr_pooled": float(((s_cal >= tau0) & (y_cal == 0)).sum() / (y_cal == 0).sum())}
    for rule, t in taus.items():
        m = metrics_at_thresholds(y_test, s_test, {BUDGET: t}, budgets=(BUDGET,))[BUDGET]
        rec[rule] = {"tau": t, "fpr": m["realized_fpr"], "recall": m["recall"], "precision": m["precision"],
                     "tp": m["tp"], "fp": m["fp"], "n_pos": int((~neg).sum()), "n_neg": int(neg.sum()),
                     "fp_near": int(((s_test >= t) & neg & t_near).sum()), "n_near": int((neg & t_near).sum()),
                     "fpr_near": float(((s_test >= t) & neg & t_near).sum() / (neg & t_near).sum()),
                     "fpr_ordinary": float(((s_test >= t) & neg & ~t_near).sum() / (neg & ~t_near).sum())}
    return rec


def block_sizes(blocks) -> dict:
    """Transactions per sampled background block, from an archive RPC (empty without one)."""
    try:
        from core.env import load_dotenv, resolve_rpc
        from core.rpc import RpcClient
        load_dotenv()
        client = RpcClient(resolve_rpc("mainnet"), timeout=30)
        return {int(b): int(client.call("eth_getBlockTransactionCountByNumber", [hex(int(b))]), 16)
                for b in sorted(blocks)}
    except Exception as e:  # noqa: BLE001 - optional context for the alert-volume estimate
        print(f"block sizes unavailable: {e}")
        return {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / ".cache" / "revision" / "threshold.json")
    ap.add_argument("--seeds", type=int, default=50)
    args = ap.parse_args()

    ds = build_dataset(CACHE)
    by_hash = {r["tx_hash"]: r for r in ds["rows"]}
    near = {h for h, r in by_hash.items() if r["label"] != "attack" and _is_near_negative(r["row"])}
    rows = [{"tx_hash": r["tx_hash"], "label": r["label"], "chain": r["chain"], "block": r["block"],
             "incident_id": r["incident_id"]} for r in ds["rows"]]
    groups = build_groups(rows)
    background = [h for h, r in by_hash.items() if r["label"] != "attack"]

    split = json.loads(SPLIT.read_text(encoding="utf-8"))["partitions"]
    frozen = evaluate_split(ds, by_hash, near, groups, list(split["fit"]), list(split["calibration"]),
                            list(split["test"]), seed=42)
    print("frozen", {r: (frozen[r]["fpr"], frozen[r]["recall"]) for r in RULES}, flush=True)

    runs = []
    for seed in range(args.seeds):
        p = split_rows(rows, seed=seed).partitions
        rec = evaluate_split(ds, by_hash, near, groups, list(p["fit"]), list(p["calibration"]), list(p["test"]), seed)
        runs.append(rec)
        print(seed, {r: (round(rec[r]["fpr"], 4), round(rec[r]["recall"], 3)) for r in RULES}, flush=True)

    def agg(vals):
        a = np.asarray(vals, dtype=float)
        return {"median": float(np.median(a)), "p2.5": float(np.percentile(a, 2.5)),
                "p97.5": float(np.percentile(a, 97.5))}

    summary: dict = {"frozen_split": frozen}
    for rule in RULES:
        summary[rule] = {k: agg([r[rule][k] for r in runs]) for k in ("fpr", "recall", "precision", "fpr_near",
                                                                      "fpr_ordinary")}
        summary[rule]["within_budget_frac"] = float(np.mean([r[rule]["fpr"] <= BUDGET for r in runs]))
    summary["pooled_cal_to_test_gap"] = agg([r["pooled"]["fpr"] - r["cal_fpr_pooled"] for r in runs])
    summary["pooled_cal_fpr"] = agg([r["cal_fpr_pooled"] for r in runs])
    summary["n_cal_blocks"] = agg([r["n_cal_blocks"] for r in runs])
    sizes = block_sizes({by_hash[h]["block"] for h in background})
    med = float(np.median(list(sizes.values()))) if sizes else None
    summary["alert_volume"] = {
        "near_negative_share": len(near) / len(background),
        "block_tx_count_median": med, "block_tx_counts": sizes,
        "alerts_per_block": {rule: (med * summary[rule]["fpr"]["median"] if med else None) for rule in RULES},
        "alerts_per_block_frozen": {rule: (med * frozen[rule]["fpr"] if med else None) for rule in RULES},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"summary": summary, "runs": runs}, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "frozen_split"}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Stage 1 (RQ1) analyses added in the revision.

    python -m eval.revision.stage1 --out .cache/revision/stage1.json

All analyses use the frozen trace cache and the frozen grouped-v2 split (local only):
  1. view ablation (single view, leave one out) and internal selector baselines on the frozen split,
     with thresholds from the calibration partition only;
  2. stratified bootstrap intervals for AUPRC on the frozen test set;
  3. repeated splits: the same deterministic partitioner with block/incident grouping (grouped) and
     with every transaction its own group (leaky), over the same seeds, so leakage is measured paired;
  4. calibration: ECE and Brier score on the test partition before and after temperature scaling;
  5. out-of-fold Stage 1 scores for the fixed-20 queue (grouped 5-fold cross-fitting).
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from core.fusion import calibrate_temperature, expected_calibration_error, fit_logistic_fusion
from core.protocol import SCREENING_VIEWS
from eval.e1_baselines import BASELINE_SCORERS, BASELINES
from eval.e1_common import average_precision, metrics_at_thresholds, select_fpr_thresholds
from eval.e1_train import _view_matrix, build_dataset
from eval.grouped_split_v2 import build_groups, split_rows

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "eval" / "results" / "runs"
CACHE = ROOT / "eval" / "results" / "e1_trace_cache.jsonl"
SPLIT = RUNS / "p7-screening-split-corrected-20260912-r2" / "split_manifest.json"
MODEL_RUN = RUNS / "p7-screening-model-corrected-20260912-r2"
COHORTS = RUNS / "p7-near-negative-20260912-r1" / "cohort_manifest.json"
FIXED20 = ROOT / "eval" / "rq3" / "fixed20_cases.json"
BUDGET = 0.01
# state_delta is never observed in the trace cache (evaluate_all(trace, {})), so it is constant zero.
ACTIVE_VIEWS = ("call_structure", "token_flow", "economic")


def _labels(by_hash: dict, hashes) -> np.ndarray:
    return np.array([by_hash[h]["label"] == "attack" for h in hashes], dtype=float)


def _matrix(ds: dict, hashes, views) -> np.ndarray:
    full = _view_matrix(ds, list(hashes))
    return full[:, [SCREENING_VIEWS.index(v) for v in views]]


def fit_eval(ds, by_hash, fit_h, cal_h, test_h, views=SCREENING_VIEWS, seed=42, calibrate=True):
    fit_x, cal_x, test_x = (_matrix(ds, h, views) for h in (fit_h, cal_h, test_h))
    fit_y, cal_y, test_y = (_labels(by_hash, h) for h in (fit_h, cal_h, test_h))
    model = fit_logistic_fusion(fit_x, fit_y, view_names=tuple(views), seed=seed)
    if calibrate:
        model = calibrate_temperature(model, cal_x, cal_y)
    thr = select_fpr_thresholds(cal_y, model.predict(cal_x), budgets=(BUDGET,))
    scores = model.predict(test_x)
    m = metrics_at_thresholds(test_y, scores, thr, budgets=(BUDGET,))
    return model, thr[BUDGET], scores, test_y, m


def _summ(m: dict) -> dict:
    op = m[BUDGET]
    return {"auprc": m["auc_pr"], "recall": op["recall"], "precision": op["precision"],
            "fpr": op["realized_fpr"], "tp": op["tp"], "fp": op["fp"]}


def bootstrap_auprc(y, s, n=2000, seed=7) -> list[float]:
    rng = np.random.default_rng(seed)
    pos, neg = np.flatnonzero(y == 1), np.flatnonzero(y == 0)
    vals = []
    for _ in range(n):
        idx = np.concatenate([rng.choice(pos, len(pos)), rng.choice(neg, len(neg))])
        vals.append(average_precision(y[idx], s[idx]))
    return [float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))]


def brier(p, y) -> float:
    return float(np.mean((np.asarray(p) - np.asarray(y)) ** 2))


def _hash_fold(key: str, k: int) -> int:
    return int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) % k


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / ".cache" / "revision" / "stage1.json")
    ap.add_argument("--seeds", type=int, default=50)
    args = ap.parse_args()

    ds = build_dataset(CACHE)
    by_hash = {r["tx_hash"]: r for r in ds["rows"]}
    split = json.loads(SPLIT.read_text(encoding="utf-8"))
    fit_h, cal_h, test_h = (split["partitions"][p] for p in ("fit", "calibration", "test"))
    cohorts = json.loads(COHORTS.read_text(encoding="utf-8"))
    out: dict = {"n_rows": len(ds["rows"])}

    # 0. reproduce the frozen model and check against the stored predictions
    model, tau, scores, y, m = fit_eval(ds, by_hash, fit_h, cal_h, test_h)
    stored = {r["tx_hash"]: r["score"] for r in
              json.loads((MODEL_RUN / "test_predictions.json").read_text(encoding="utf-8"))}
    out["reproduction_max_abs_diff"] = float(max(abs(stored[h] - s) for h, s in zip(test_h, scores)))
    out["frozen"] = {**_summ(m), "tau": tau, "auprc_ci95": bootstrap_auprc(y, scores),
                     "weights": model.weights, "offset": model.offset}
    view_cover = {v: float(np.mean(_matrix(ds, list(by_hash), (v,))[:, 0] > 0)) for v in SCREENING_VIEWS}
    out["view_nonzero_fraction"] = view_cover

    # per-cohort AUPRC with bootstrap intervals
    idx = {h: i for i, h in enumerate(test_h)}
    coh = {}
    for name, neg_key in (("ordinary", "ordinary_negative_test"), ("near_negative", "near_negative_test")):
        sel = [idx[h] for h in cohorts["positive_test"] + cohorts[neg_key]]
        coh[name] = {"auprc": average_precision(y[sel], scores[sel]),
                     "auprc_ci95": bootstrap_auprc(y[sel], scores[sel]),
                     "fp": int(((scores[sel] >= tau) & (y[sel] == 0)).sum()), "n_neg": int((y[sel] == 0).sum())}
    out["cohorts"] = coh

    # 1. ablation and baselines on the frozen split
    abl = {}
    for views in [ACTIVE_VIEWS] + [(v,) for v in ACTIVE_VIEWS] + \
            [tuple(x for x in ACTIVE_VIEWS if x != v) for v in ACTIVE_VIEWS]:
        _, _, s_v, y_v, m_v = fit_eval(ds, by_hash, fit_h, cal_h, test_h, views=views)
        abl["+".join(views)] = {**_summ(m_v), "auprc_ci95": bootstrap_auprc(y_v, s_v)}
    out["ablation"] = abl
    base = {}
    y_cal = _labels(by_hash, cal_h)
    for name in BASELINES:
        f = BASELINE_SCORERS[name]
        sc = np.array([f(by_hash[h]["row"]) for h in cal_h])
        st = np.array([f(by_hash[h]["row"]) for h in test_h])
        thr = select_fpr_thresholds(y_cal, sc, budgets=(BUDGET,))
        base[name] = {**_summ(metrics_at_thresholds(y, st, thr, budgets=(BUDGET,))),
                      "auprc_ci95": bootstrap_auprc(y, st)}
    out["baselines"] = base

    # 2./3. repeated grouped vs leaky splits with the same partitioner and seeds
    rows = [{"tx_hash": r["tx_hash"], "label": r["label"], "chain": r["chain"], "block": r["block"],
             "incident_id": r["incident_id"]} for r in ds["rows"]]
    leaky_rows = [{"tx_hash": r["tx_hash"], "label": r["label"]} for r in rows]
    rep = {"grouped": [], "leaky": []}
    for seed in range(args.seeds):
        for kind, rr in (("grouped", rows), ("leaky", leaky_rows)):
            sm = split_rows(rr, seed=seed)
            p = sm.partitions
            _, _, _, _, m_s = fit_eval(ds, by_hash, list(p["fit"]), list(p["calibration"]), list(p["test"]), seed=seed)
            rep[kind].append({"seed": seed, **_summ(m_s), "n_pos": int(_labels(by_hash, p["test"]).sum())})

    def agg(xs, key):
        a = np.array([x[key] for x in xs])
        return {"median": float(np.median(a)), "p2.5": float(np.percentile(a, 2.5)),
                "p97.5": float(np.percentile(a, 97.5)), "mean": float(a.mean())}
    out["repeated"] = {k: {key: agg(v, key) for key in ("auprc", "recall", "fpr", "precision")}
                       for k, v in rep.items()}
    diff = np.array([g["auprc"] - l["auprc"] for g, l in zip(rep["grouped"], rep["leaky"])])
    out["repeated"]["paired_auprc_diff_grouped_minus_leaky"] = {
        "median": float(np.median(diff)), "p2.5": float(np.percentile(diff, 2.5)),
        "p97.5": float(np.percentile(diff, 97.5)), "frac_negative": float(np.mean(diff < 0))}
    out["repeated"]["fpr_over_budget_frac"] = {
        k: float(np.mean([x["fpr"] > BUDGET for x in v])) for k, v in rep.items()}
    out["repeated_runs"] = rep

    # 4. calibration: same fit, with and without temperature scaling
    raw, tau_raw, s_raw, _, m_raw = fit_eval(ds, by_hash, fit_h, cal_h, test_h, calibrate=False)
    out["calibration"] = {
        "temperature": float(raw.weights["call_structure"] / model.weights["call_structure"]),
        "ece_test_raw": expected_calibration_error(s_raw, y), "ece_test_cal": expected_calibration_error(scores, y),
        "brier_test_raw": brier(s_raw, y), "brier_test_cal": brier(scores, y),
        "ece_cal_raw": expected_calibration_error(raw.predict(_matrix(ds, cal_h, SCREENING_VIEWS)), y_cal),
        "ece_cal_cal": expected_calibration_error(model.predict(_matrix(ds, cal_h, SCREENING_VIEWS)), y_cal),
        "same_ranking": bool(np.array_equal(np.argsort(-s_raw, kind="stable"), np.argsort(-scores, kind="stable"))),
        "same_candidates": bool(np.array_equal(s_raw >= tau_raw, scores >= tau)),
    }
    bins = np.linspace(0, 1, 11)
    rel = []
    for lo, hi in zip(bins[:-1], bins[1:]):
        msk = (scores >= lo) & (scores < hi if hi < 1 else scores <= hi)
        if msk.any():
            rel.append({"lo": float(lo), "hi": float(hi), "n": int(msk.sum()),
                        "conf": float(scores[msk].mean()), "acc": float(y[msk].mean())})
    out["calibration"]["reliability_test"] = rel

    # 5. out-of-fold scores for the fixed-20 queue (grouped 5-fold cross-fitting)
    groups = build_groups(rows)
    k = 5
    fold = {h: _hash_fold(groups[h], k) for h in groups}
    fixed = json.loads(FIXED20.read_text(encoding="utf-8"))["cases"]
    fixed_hash = {v["tx_hash"].lower(): name for name, v in fixed.items()}
    lower = {h.lower(): h for h in by_hash}
    oof = {}
    for f in range(k):
        test_f = [h for h in by_hash if fold[h] == f]
        train = [h for h in by_hash if fold[h] != f]
        cal_f = [h for h in train if _hash_fold("cal:" + groups[h], 5) == 0]
        fit_f = [h for h in train if _hash_fold("cal:" + groups[h], 5) != 0]
        _, tau_f, s_f, y_f, m_f = fit_eval(ds, by_hash, fit_f, cal_f, test_f)
        for h, s in zip(test_f, s_f):
            if h.lower() in fixed_hash:
                oof[fixed_hash[h.lower()]] = {"fold": f, "score": float(s), "tau": tau_f, "flagged": bool(s >= tau_f)}
        oof.setdefault("_folds", []).append({"fold": f, **_summ(m_f), "tau": tau_f})
    missing = [n for h, n in fixed_hash.items() if h not in lower]
    flagged = sum(1 for n, v in oof.items() if n != "_folds" and v["flagged"])
    out["fixed20_oof"] = {"cases": oof, "flagged": flagged, "n": len(fixed) - len(missing), "missing": missing}

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    brief = {k: v for k, v in out.items() if k not in ("repeated_runs",)}
    brief["fixed20_oof"] = {"flagged": flagged, "n": out["fixed20_oof"]["n"], "missing": missing}
    print(json.dumps(brief, indent=1, default=float))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

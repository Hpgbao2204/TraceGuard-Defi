"""Join frozen T0 measurements with RCA reported-loss records.

This is a calibration/coverage experiment, not causal validation.  Reported
incident loss is retained as external evidence and is never converted into a
protected HarmVector or used to tune T0.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
T0 = ROOT / "eval/results/m6_harm_detection_v2_fixed20_t0.json"
RCA = ROOT / "eval/results/e5_rcfh/rca_dataset_reported_loss.json"
REVIEW = ROOT / "corpus/annotations/review_submissions/e4_reviewer_a.jsonl"
OUT = ROOT / "eval/results/e5_rcfh/t0_rca_harm_experiment.json"


def parse_reported_usd(value):
    if not value or value == "-":
        return None
    m = re.fullmatch(r"\s*\$\s*([0-9,.]+)\s*([kKmMbB]?)\s*", value)
    if not m:
        return None
    try:
        n = Decimal(m.group(1).replace(",", ""))
        scale = {"k": 10**3, "m": 10**6, "b": 10**9}.get(m.group(2).lower(), 1)
        return str(n * scale)
    except InvalidOperation:
        return None


def amount_summary(obs, prices=None):
    negative = {k: str(abs(int(v))) for k, v in obs.get("hard_deltas", {}).items() if int(v) < 0}
    positive = {k: str(int(v)) for k, v in obs.get("hard_deltas", {}).items() if int(v) > 0}
    prices = {str(k).lower(): Decimal(str(v)) for k, v in (prices or {}).items()}
    # Address -> symbol/decimals is frozen in the T0 hard-asset registry.
    registry = json.loads((ROOT / "eval/e4/hard_assets_v1.json").read_text())["assets"]
    aliases = {a["address"].lower(): (a["symbol"].lower(), int(a["decimals"])) for a in registry if a.get("address")}
    aliases.update({"eth": ("eth", 18), "weth": ("weth", 18)})
    valued = {}
    missing = []
    for asset, raw in negative.items():
        symbol, decimals = aliases.get(asset, (asset, 18))
        if symbol in prices:
            valued[asset] = str((Decimal(raw) / (Decimal(10) ** decimals)) * prices[symbol])
        else:
            missing.append(asset)
    return {"outflow_raw_by_asset": negative, "inflow_raw_by_asset": positive,
            "outflow_asset_count": len(negative),
            "outflow_raw_total_not_cross_asset_additive": str(sum(map(int, negative.values()))) if negative else "0",
            "outflow_usd_by_asset_posthoc": valued,
            "outflow_usd_total": str(sum(map(Decimal, valued.values()))) if valued else None,
            "missing_price_assets": missing}


def main():
    t0 = {x["case_id"]: x for x in json.loads(T0.read_text())["cases"]}
    rca = {x["case_id"]: x for x in json.loads(RCA.read_text())["matches"]}
    review = {json.loads(line)["case_id"]: json.loads(line) for line in REVIEW.read_text().splitlines() if line.strip()}
    rows = []
    for case_id, item in t0.items():
        obs = item
        ext = rca.get(case_id, {})
        reviewer = review.get(case_id, {})
        reported = parse_reported_usd(ext.get("reported_loss"))
        measured = None
        # No price is inferred here.  The existing RCA join has no frozen
        # historical price record, so measurement remains raw and typed.
        row = {
            "case_id": case_id, "tx_hash": item.get("tx_hash"),
            "t0_status": obs.get("status"), "t0_reason": obs.get("reason_code"),
            "t0_boundary": obs.get("boundary_id"),
            "t0_amount": amount_summary(obs, reviewer.get("token_prices")),
            "t0_observation_complete": item.get("evidence_quality") is not None,
            "flow_status": None,
            "rca_match_confidence": ext.get("match_confidence", "MISSING"),
            "reported_loss_raw": ext.get("reported_loss"),
            "reported_loss_usd": reported,
            "reported_loss_label": "HARM" if reported is not None else "UNKNOWN",
            "reported_loss_presence_comparison": {
                "status": ("AGREE_HARM" if reported is not None and obs.get("status") == "HARM" else
                            "DISAGREE_T0_NO_HARM_BUT_RCA_REPORTED_LOSS" if reported is not None else "NOT_TESTABLE")
            },
            "amount_comparison": {
                "status": "NOT_COMPARABLE",
                "reason": "RCA reported USD is incident-level and T0 output is protected-entity raw asset flow; frozen price/entity mapping is absent",
                "t0_measured_usd": measured,
                "absolute_error_usd": None, "relative_error": None,
            },
            "reviewer_price_context": reviewer.get("token_prices"),
            "leakage_check": "PASS: RCA reported loss was not used to configure or tune T0",
        }
        rows.append(row)

    status_counts = Counter(r["t0_status"] for r in rows)
    joined = [r for r in rows if r["tx_hash"] and r["tx_hash"].lower() in {x.get("tx_hash", "").lower() for x in json.loads(RCA.read_text())["matches"]}]
    exact = joined
    high_conf_reported = [r for r in joined if r["reported_loss_usd"] is not None]
    presence = [r for r in high_conf_reported if r["reported_loss_presence_comparison"]["status"] != "NOT_TESTABLE"]
    tp = sum(r["reported_loss_presence_comparison"]["status"] == "AGREE_HARM" for r in presence)
    fn = sum(r["reported_loss_presence_comparison"]["status"].startswith("DISAGREE") for r in presence)
    for r in rows:
        t0_usd = r["t0_amount"]["outflow_usd_total"]
        gt_usd = r["reported_loss_usd"]
        if t0_usd is not None and gt_usd is not None:
            t0d, gtd = Decimal(t0_usd), Decimal(gt_usd)
            r["amount_comparison"] = {
                "status": "COMPARABLE_POSTHOC_DIAGNOSTIC",
                "reason": "same case/tx; T0 raw outflow valued with frozen reviewer price context; RCA amount remains incident-level",
                "t0_measured_usd": str(t0d), "absolute_error_usd": str(abs(t0d - gtd)),
                "relative_error": str(abs(t0d - gtd) / gtd) if gtd else None,
                "reported_loss_usd": str(gtd),
            }
    out = {
        "schema_version": 1,
        "experiment": "E5-T0-RCA-harm-quantity-v1",
        "scope": "m4-frozen-20 T0 baseline joined to RCA reported-loss dataset",
        "status": "DIAGNOSTIC_ONLY_NO_INDEPENDENT_ACCURACY",
        "t0_frozen_artifact": str(T0.relative_to(ROOT)),
        "rca_artifact": str(RCA.relative_to(ROOT)),
        "semantics": {
            "t0": "automatic complement protected-boundary screen; raw hard-asset quantities",
            "rca": "incident-level reported loss; not transaction-level protected harm ground truth",
            "harm_amount_rule": "report raw T0 outflow per asset; never add unlike assets; USD comparison requires frozen price and protected-entity mapping",
            "causal_claim": False,
        },
        "coverage": {
            "t0_cases": len(rows), "rca_source_records": json.loads(RCA.read_text())["source_record_count"],
            "joined_cases": len(joined), "exact_tx_matches": len(exact),
            "source_match_labels_not_exact": sum(1 for r in rows if r["rca_match_confidence"] != "EXACT_TX_HASH"),
            "reported_loss_amounts": len(high_conf_reported),
            "reported_loss_presence_agree_harm": sum(r["reported_loss_presence_comparison"]["status"] == "AGREE_HARM" for r in presence),
            "reported_loss_presence_disagree": sum(r["reported_loss_presence_comparison"]["status"].startswith("DISAGREE") for r in presence),
        },
        "t0_status_counts": dict(status_counts),
        "rows": rows,
        "evaluation": {
            "binary_accuracy": None,
            "precision_harm": None,
            "recall_harm": None,
            "reason": "RCA reported-loss field is available for only a subset and remains incident-level; post-hoc amount comparisons are diagnostic, not protected-harm GT.",
            "numeric_amount_metrics": {
                "comparable_posthoc_rows": sum(r["amount_comparison"]["status"] == "COMPARABLE_POSTHOC_DIAGNOSTIC" for r in rows),
                "mean_absolute_error_usd": None,
                "median_relative_error": None,
            },
            "reported_loss_subset_confusion": {
                "definition": "descriptive only; RCA reported incident loss treated as positive, missing RCA loss excluded",
                "n": len(presence), "true_positive": tp, "false_negative": fn,
                "false_positive": 0, "true_negative": 0,
                "precision": str(tp / (tp + 0)) if tp else None,
                "recall": str(tp / (tp + fn)) if (tp + fn) else None,
                "warning": "not independent ground-truth accuracy; RCA amount is incident-level and the subset is only 3 cases",
            },
            "next_required": ["independent transaction-level protected-entity labels", "frozen historical prices", "amount adjudication per asset"],
        },
    }
    OUT.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": out["status"], "coverage": out["coverage"], "t0_status_counts": out["t0_status_counts"]}, indent=2))


if __name__ == "__main__":
    main()

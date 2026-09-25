"""Materialize a blinded, stratified review queue from the candidate pool."""
from __future__ import annotations
import hashlib, json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "eval/results/e5_rcfh/defihacklabs_t0_candidate_pool.json"
OUT = ROOT / "eval/results/e5_rcfh/transaction_harm_gold_review_queue.json"


def main():
    source = json.loads(SRC.read_text())
    groups = defaultdict(list)
    for row in source["candidates"]:
        family = row["reported_root_cause"]["family"]
        groups[family].append(row)
    # Stable ordering and round-robin assignment prevent family/order drift.
    for family in groups:
        groups[family].sort(key=lambda r: hashlib.sha256(r["candidate_id"].encode()).hexdigest())
    ordered = []
    while any(groups.values()):
        for family in sorted(groups):
            if groups[family]: ordered.append(groups[family].pop(0))
    split = {"development": 20, "validation": 30, "held_out_test": 30}
    cases = []
    for i, row in enumerate(ordered):
        acc = 0
        split_name = "held_out_test"
        for name, count in split.items():
            acc += count
            if i < acc:
                split_name = name; break
        cases.append({
            "review_id": f"thg-{i+1:03d}", "split": split_name,
            "candidate_id": row["candidate_id"], "tx_hash": row["transaction"]["tx_hashes"][0],
            "chain": row["transaction"]["chain"], "protocol": row["incident"]["protocol"],
            "reported_loss_usd": row["incident"]["loss_usd"],
            "reported_family": row["reported_root_cause"]["family"],
            "source_url": row["provenance"]["source_url"],
            "review_status": "PENDING_HUMAN_REVIEW",
            "harm_gold": {
                "label": "PENDING", "protected_entity": None, "harm_type": None,
                "asset": None, "before_raw": None, "after_raw": None,
                "delta_raw": None, "valuation_usd": None, "valuation_source": None,
                "evidence": [], "reviewer": None,
            },
            "b2_status": "NOT_RUN", "t0_status": "NOT_RUN",
        })
    out = {
        "schema_version": 1, "artifact": "transaction-harm-gold-review-queue-v1",
        "source_artifact": str(SRC.relative_to(ROOT)),
        "selection_independent_of_t0": True,
        "gold_label_policy": "Only adjudicated transaction-level protected harm enters GOLD; incident reported loss is context only.",
        "split_policy": split, "case_count": len(cases), "cases": cases,
        "required_review_fields": ["protected_entity", "harm_type", "asset", "before_raw", "after_raw", "delta_raw", "valuation_usd", "valuation_source", "evidence", "reviewer"],
        "status": "PENDING_HUMAN_REVIEW",
    }
    OUT.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"case_count": len(cases), "splits": {k: sum(x["split"] == k for x in cases) for k in split}, "status": out["status"]}, indent=2))


if __name__ == "__main__": main()

"""Materialize only strong relation leads for fresh human review.

The output is intentionally not a verified-benign benchmark: human reviewers
must still establish same-protocol relation, mechanism, and label.
"""
from __future__ import annotations
import csv, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEADS = ROOT / "eval/results/hard_negative_queue_v2_leads.json"
OUT = ROOT / "eval/results/hard_negative_review_queue_v2.csv"

def main() -> None:
    data = json.loads(LEADS.read_text(encoding="utf-8"))
    rows = []
    for item in data["candidates"]:
        if item["relation_strength"] != "strong_exact_anchor_overlap":
            continue
        rows.append({
            "attack_case_id": item["incident_case_id"],
            "incident_tx_hash": item["incident_tx_hash"],
            "attack_tx_hash": item["incident_tx_hash"],
            "attack_block": item["incident_block"],
            "candidate_tx_hash": item["candidate_tx_hash"],
            "candidate_block": item["candidate_block"],
            "block_distance": item["block_distance"],
            "window_blocks": 216000,
            "within_window": item["within_window"],
            "relation_evidence": item["relation_evidence"],
            "shared_anchor_addresses": json.dumps(
                item["shared_non_infrastructure_addresses"], separators=(",", ":")),
            "same_protocol": "pending",
            "same_contract_family": "pending",
            "review_status": "pending",
            "verified_benign": "unknown",
        })
    fields = list(rows[0]) if rows else []
    with OUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        if fields:
            writer.writeheader(); writer.writerows(rows)
    print(json.dumps({"rows": len(rows), "status": "pending_human_review"}))

if __name__ == "__main__":
    main()

"""Rank observed seam candidates for human review; never authorizes replay."""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAPPING = ROOT / "eval/results/e5_rcfh/claim_mapping_v1.json"
OUT = ROOT / "eval/results/e5_rcfh/seam_review_ranking.json"

def main() -> None:
    mapping = json.loads(MAPPING.read_text())
    ranked = []
    for item in mapping["cases"]:
        if item["status"] != "MAPPED_CANDIDATE":
            continue
        groups = item["seam_groups_considered"]
        for g in groups:
            # Lower candidate count and stronger selector/operator specificity
            # make review cheaper, not scientifically more causal.
            specificity = 3 if len(groups) == 1 else 2 if len(groups) <= 2 else 1
            ranked.append({
                "case_id": item["case_id"],
                "group_id": g["group_id"],
                "operator_type": g["type"],
                "callee": g["callee"],
                "candidate_group_count": len(groups),
                "review_priority": specificity,
                "status": "OBSERVED_SEAM_ONLY",
                "replay_authorized": False,
                "reason": "trace-derived candidate; claim boundary, victim, and harm point remain unreviewed",
            })
    ranked.sort(key=lambda x: (-x["review_priority"], x["case_id"], x["group_id"]))
    result = {
        "schema_version": 1,
        "artifact": "e5-seam-review-ranking",
        "corpus_id": "m4-frozen-20",
        "policy": "ranking assists review; it does not select a root-cause seam",
        "candidate_count": len(ranked),
        "recommended_first_review": [
            "defihacklabs-muredistribution-2026-05-21",
            "defihacklabs-veth-2024-11-14",
            "defihacklabs-sizeflashloanlooping-2025-08-15",
        ],
        "seams": ranked,
    }
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"candidate_count": len(ranked), "first": result["recommended_first_review"]}, indent=2))

if __name__ == "__main__": main()

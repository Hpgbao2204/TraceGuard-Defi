"""E4 preflight for E5-localized candidates; never runs a mutation."""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "eval/results/e5_rcfh/e4_candidate_preflight.json"


def main() -> None:
    mapping = json.loads((ROOT / "eval/results/e5_rcfh/claim_mapping_v1.json").read_text())
    cases = []
    for item in mapping["cases"]:
        if item["status"] != "MAPPED_CANDIDATE":
            continue
        seam = json.loads((ROOT / "eval/results/e5_rcfh/seam_groups" / f"{item['case_id']}.json").read_text())
        candidate = [g for g in seam["seam_groups"] if g["type"] in item["mapped_operator_types"]]
        reason = "REVIEW_AND_SHAM_REQUIRED"
        if len(candidate) == 0:
            reason = "MAPPING_STALE_NO_SEAM"
        elif len(candidate) > 1:
            reason = "MULTIPLE_GROUPS_REQUIRES_CLAIM_BOUNDARY_REVIEW"
        cases.append({
            "case_id": item["case_id"],
            "claim_factor_labels": item["claim_factor_labels"],
            "candidate_operator_types": item["mapped_operator_types"],
            "candidate_group_count": len(candidate),
            "candidate_group_ids": [g["group_id"] for g in candidate],
            "status": "CANDIDATE_NOT_AUTHORIZED",
            "reason": reason,
            "same_kind_sham": "NOT_RUN",
            "counterfactual_replay": "NOT_RUN",
            "causal_verdict": None,
        })
    result = {
        "schema_version": 1,
        "artifact": "e5-e4-candidate-preflight",
        "corpus_id": "m4-frozen-20",
        "scope": "E4 preflight only; no mutation or causal replay",
        "candidate_count": len(cases),
        "cases": cases,
        "authorization_policy": "human claim-to-victim-to-seam review and same-kind sham are required before E4 replay",
    }
    OUT.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"candidate_count": len(cases), "replay": "NOT_RUN", "cases": [{"case_id": x["case_id"], "reason": x["reason"]} for x in cases]}, indent=2))


if __name__ == "__main__": main()

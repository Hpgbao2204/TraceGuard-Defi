"""Build a fail-closed human review packet for mapped E5 candidates.

This does not select a victim, seam, or harm-write location.  It only joins
the machine candidate list with available claim text so a reviewer can make
those decisions from source evidence.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAPPING = ROOT / "eval/results/e5_rcfh/claim_mapping_v1.json"
CROSSWALK = ROOT / "eval/results/e5_rcfh/label_crosswalk.json"
SEAMS = ROOT / "eval/results/e5_rcfh/seam_groups"
OUT = ROOT / "eval/results/e5_rcfh/claim_boundary_review_packet.json"


def main() -> None:
    mapping = json.loads(MAPPING.read_text())
    crosswalk = {x["case_id"]: x for x in json.loads(CROSSWALK.read_text())["cases"]}
    packet = []
    for item in mapping["cases"]:
        if item["status"] != "MAPPED_CANDIDATE":
            continue
        case_id = item["case_id"]
        row = crosswalk[case_id]
        claims = {}
        for source, payload in row["sources"].items():
            if payload.get("claim") is not None:
                claims[source] = payload["claim"]
        seam_doc = json.loads((SEAMS / f"{case_id}.json").read_text())
        groups = [g for g in seam_doc["seam_groups"] if g["type"] in item["mapped_operator_types"]]
        packet.append({
            "case_id": case_id,
            "review_status": "PENDING_HUMAN_REVIEW",
            "claim_factor_labels": item["claim_factor_labels"],
            "candidate_operator_types": item["mapped_operator_types"],
            "claims": claims,
            "candidate_seam_groups": groups,
            "required_fields": {
                "victim_or_asset_addresses": "REQUIRED_FROM_SOURCE",
                "harm_write_trace_index": "REQUIRED_FROM_TRACE_REVIEW",
                "selected_seam_group_ids": "REQUIRED_FROM_CLAIM_BOUNDARY_REVIEW",
                "rejected_seam_group_ids": "REQUIRED_WITH_REASONS",
            },
            "selected_seam_group_ids": [],
            "victim_or_asset_addresses": [],
            "harm_write_trace_index": None,
            "same_kind_sham": "NOT_RUN",
            "counterfactual_replay": "NOT_RUN",
            "causal_verdict": None,
        })
    result = {
        "schema_version": 1,
        "artifact": "e5-claim-boundary-review-packet",
        "corpus_id": "m4-frozen-20",
        "policy": "review packet only; no inferred boundary or replay authorization",
        "candidate_count": len(packet),
        "cases": packet,
    }
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(OUT), "candidate_count": len(packet), "status": "PENDING_HUMAN_REVIEW"}, indent=2))


if __name__ == "__main__":
    main()

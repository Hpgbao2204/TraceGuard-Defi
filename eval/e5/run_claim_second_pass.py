"""Escalate legacy seam mismatches for claim-bound review, fail closed."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "eval/results/e5_rcfh/claim_second_pass_admission.json"


def main() -> None:
    old = json.loads((ROOT / "eval/results/e5_rcfh/claim_semantic_admission.json").read_text())
    schema = {x["case_id"]: x for x in json.loads(
        (ROOT / "eval/results/e5_rcfh/claim_schema_v2.json").read_text()
    )["cases"]}
    rows = []
    for item in old["cases"]:
        if item["status"] not in {"CLAIM_SEAM_MISMATCH", "RAW_SEAM_MISSING"}:
            continue
        claim = schema[item["case_id"]]
        if item["raw_seam_group_count"]:
            status = "SECOND_PASS_SEMANTIC_REVIEW_REQUIRED"
            reason = "raw seam exists, but claim-bound dependency/data-flow is not materialized"
        else:
            status = "SECOND_PASS_RAW_SEAM_MISSING"
            reason = "no raw executable seam available for second-pass localization"
        rows.append({
            "case_id": item["case_id"],
            "legacy_status": item["status"],
            "second_pass_status": status,
            "reason": reason,
            "raw_operator_types": item["raw_operator_types"],
            "candidate_interventions": [x.get("type") for x in claim.get("candidate_interventions", [])],
            "root_mechanism": claim.get("root_mechanism", {}).get("statement"),
            "vulnerable_boundary": claim.get("vulnerable_boundary"),
            "causal_variable": claim.get("causal_variable"),
            "dependency_path": claim.get("dependency_path"),
            "replay_authorized": False,
            "causal_verdict": None,
        })
    out = {
        "schema_version": 1,
        "artifact": "e5-claim-second-pass-admission",
        "policy": "legacy mismatch is escalated, never auto-promoted; claim-bound data-flow is required",
        "source_artifact": "eval/results/e5_rcfh/claim_semantic_admission.json",
        "cases": rows,
        "counts": {
            "SECOND_PASS_SEMANTIC_REVIEW_REQUIRED": sum(x["second_pass_status"] == "SECOND_PASS_SEMANTIC_REVIEW_REQUIRED" for x in rows),
            "SECOND_PASS_RAW_SEAM_MISSING": sum(x["second_pass_status"] == "SECOND_PASS_RAW_SEAM_MISSING" for x in rows),
        },
    }
    OUT.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(json.dumps(out["counts"], indent=2))


if __name__ == "__main__":
    main()

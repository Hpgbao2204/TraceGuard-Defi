"""Audit claim-to-intervention compatibility using raw seam groups."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "eval/results/e5_rcfh/claim_semantic_admission.json"

# Conservative by design: generic invariant labels do not match an AMM read.
OPERATOR_FAMILIES = {
    "flashloan_capital": {"flash_loan_protection"},
    "oracle_read": {"price_sanity_bound", "twap_price_feed", "oracle_bound"},
    "amm_reserve_read": {"price_sanity_bound", "twap_price_feed"},
    "auth_check": {"access_control", "access_control_modifier", "signature_verification", "allowance_check"},
}

def _raw_groups(case_id: str) -> list[dict]:
    path = ROOT / "eval/results/e5_rcfh/seam_groups" / f"{case_id}.json"
    if not path.exists():
        return []
    return json.loads(path.read_text()).get("seam_groups", [])


def main() -> None:
    schema = json.loads((ROOT / "eval/results/e5_rcfh/claim_schema_v2.json").read_text())
    cases = []
    for claim in schema["cases"]:
        cid = claim["case_id"]
        groups = _raw_groups(cid)
        raw_types = sorted({g.get("type") for g in groups if g.get("type")})
        intervention_types = {x.get("type") for x in claim.get("candidate_interventions", [])}
        compatible = sorted({op for op in raw_types if OPERATOR_FAMILIES.get(op, set()) & intervention_types})
        enabling = set(claim.get("enabling_factors", []))
        enabling_observed = sorted(
            op for op in raw_types
            if op == "flashloan_capital" and "f_fl" in enabling
        )
        enabling_compatible = sorted(
            op for op in compatible
            if (op == "flashloan_capital" and "f_fl" in enabling)
        )
        root_compatible = sorted(op for op in compatible if op not in enabling_compatible)
        if not raw_types:
            status, reason = "RAW_SEAM_MISSING", "NO_RAW_EXECUTABLE_SEAM_GROUP"
        elif not compatible:
            status, reason = "CLAIM_SEAM_MISMATCH", "RAW_SEAM_DOES_NOT_MANIPULATE_CLAIMED_VARIABLE"
        else:
            status, reason = "SEMANTIC_REVIEW_REQUIRED", "RAW_SEAM_AND_CLAIM_VARIABLE_REQUIRE_BOUNDARY_REVIEW"
        cases.append({
            "case_id": cid,
            "raw_seam_group_count": len(groups),
            "raw_operator_types": raw_types,
            "claim_intervention_types": sorted(intervention_types),
            "compatible_operator_types": compatible,
            "root_mechanism_compatible_operator_types": root_compatible,
            "enabling_factor_compatible_operator_types": enabling_compatible,
            "enabling_factor_observed_operator_types": enabling_observed,
            "root_verdict_namespace": "SUPPORTED_ROOT|CONTRADICTED_ROOT|PARTIAL_ROOT|NOT_TESTABLE_ROOT",
            "enabling_verdict_namespace": "SUPPORTED_ENABLING|CONTRADICTED_ENABLING|PARTIAL_ENABLING|NOT_TESTABLE_ENABLING",
            "status": status,
            "reason": reason,
            "replay_authorized": False,
        })
    artifact = {
        "schema_version": 2,
        "artifact": "e5-claim-semantic-admission",
        "corpus_id": "m4-frozen-20",
        "policy": "raw seam groups are authority; no replay authorization",
        "cases": cases,
        "counts": {status: sum(x["status"] == status for x in cases)
                   for status in sorted({x["status"] for x in cases})},
    }
    OUT.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")
    print(json.dumps(artifact["counts"], indent=2))


if __name__ == "__main__":
    main()

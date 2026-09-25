"""Phase-2 deterministic claim-to-operator candidate mapping.

Mappings are candidates for review, never adjudicated root-cause labels.
"""
from __future__ import annotations
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "eval/results/e5_rcfh/claim_mapping_v1.json"
PATTERNS = [
    (r"oracle|price|reserve|exchange.?rate", "oracle-and-price-manipulation-attacks", ["oracle_read", "amm_reserve_read"]),
    (r"flash.?loan|f_fl", "flash-loan-attacks", ["flashloan_capital"]),
    (r"reentr", "reentrancy", ["reentrancy_mutex"]),
    (r"auth|approval|signature|access", "access-control-and-authorization", ["auth_check"]),
    (r"round|precision|account|exchange rate", "arithmetic-and-accounting", ["arithmetic_guard"]),
]


def map_claim(case: dict, seam_groups: list[dict]) -> dict:
    local = case["sources"].get("defihacklabs_local_corpus", {})
    claim = local.get("claim") or {}
    factors = [str(x).lower() for x in (claim.get("factor_labels") or [])]
    # A recorded factor is the claim label. Narrative keywords are only used
    # when the source did not provide a factor; otherwise incidental mentions
    # (for example, a flash lender in an auth incident) cause false mapping.
    use_narrative = not factors or factors == ["unknown"]
    text = " ".join(map(str, [claim.get("attack_type"), *(factors if not use_narrative else []), claim.get("narrative") if use_narrative else ""])).lower()
    candidate_types: set[str] = set()
    sok = []
    for pattern, group, types in PATTERNS:
        if re.search(pattern, text):
            sok.append(group)
            candidate_types.update(types)
    if factors and factors != ["unknown"]:
        factor_types = set()
        if "f_fl" in factors: factor_types.add("flashloan_capital")
        if "f_orc" in factors: factor_types.update(("oracle_read", "amm_reserve_read"))
        if "f_auth" in factors: factor_types.add("auth_check")
        if "f_swap" in factors: factor_types.add("swap_logic")
        candidate_types = factor_types
    elif factors == ["unknown"]:
        candidate_types = set()
    detected = {g["type"] for g in seam_groups}
    mapped = sorted(candidate_types & detected)
    return {
        "case_id": case["case_id"],
        "claim_source": "defihacklabs_local_corpus" if claim else None,
        "claim_match_confidence": local.get("match_confidence", "MISSING"),
        "claim_factor_labels": claim.get("factor_labels", []),
        "candidate_sok_groups": sorted(set(sok)),
        "candidate_operator_types": sorted(candidate_types),
        "mapped_operator_types": mapped,
        "seam_groups_considered": [{"group_id": g["group_id"], "type": g["type"], "callee": g["callee"]} for g in seam_groups if g["type"] in mapped],
        "status": "MAPPED_CANDIDATE" if mapped else ("CLAIM_NOT_LOCALIZABLE" if claim else "MISSING_CLAIM"),
        "coverage_interpretation": "scanner_coverage_only",
    }


def main() -> None:
    cross = json.loads((ROOT / "eval/results/e5_rcfh/label_crosswalk.json").read_text())
    seam_dir = ROOT / "eval/results/e5_rcfh/seam_groups"
    cases = []
    for case in cross["cases"]:
        data = json.loads((seam_dir / f"{case['case_id']}.json").read_text())
        cases.append(map_claim(case, data["seam_groups"]))
    mapped = sum(bool(x["mapped_operator_types"]) for x in cases)
    result = {
        "schema_version": 1,
        "artifact": "e5-claim-mapping",
        "corpus_id": "m4-frozen-20",
        "mapping_policy": "candidate-only; human review required before intervention",
        "cases": cases,
        "coverage": {"mapped_cases": mapped, "case_count": len(cases), "fraction": mapped / len(cases) if cases else 0, "gate2_threshold": 0.60, "status": "PASS_CANDIDATE_COVERAGE" if mapped / len(cases) >= 0.60 else "FAIL_BELOW_THRESHOLD"},
    }
    OUT.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result["coverage"], indent=2))


if __name__ == "__main__": main()

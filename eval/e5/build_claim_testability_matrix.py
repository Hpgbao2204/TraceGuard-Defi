"""Materialize the F-stage claim testability matrix without replay claims."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "eval/results/e5_rcfh/claim_testability_matrix.json"


def _valid_evm_address(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 42 and
            value.startswith("0x") and all(c in "0123456789abcdefABCDEF" for c in value[2:]))


def main() -> None:
    schema = json.loads((ROOT / "eval/results/e5_rcfh/claim_schema_v2.json").read_text())
    mapping = json.loads((ROOT / "eval/results/e5_rcfh/claim_mapping_v1.json").read_text())
    mapped = {x["case_id"]: x for x in mapping["cases"]}
    rows = []
    for claim in schema["cases"]:
        case_id = claim["case_id"]
        boundary = claim.get("vulnerable_boundary") or {}
        target = claim.get("protected_target") or []
        interventions = claim.get("candidate_interventions") or []
        mapping_row = mapped.get(case_id, {})
        localizable = bool(boundary.get("causal_calls"))
        valid_targets = [x for x in target if isinstance(x, dict) and _valid_evm_address(x.get("address"))]
        target_observation_defined = bool(valid_targets) and bool(claim.get("harm_definition"))
        candidate_intervention = any(x.get("applicability") == "supported" for x in interventions)
        rows.append({
            "case_id": case_id,
            "root_mechanism": claim.get("root_mechanism", {}).get("statement"),
            "ontology_labels": claim.get("root_mechanism", {}).get("ontology_labels", []),
            "enabling_factors": claim.get("enabling_factors", []),
            "localizable": {"status": "PASS" if localizable else "NOT_TESTABLE_LOCALIZATION",
                            "source": "claim_schema_v2"},
            "target_effect_defined": {"status": "PASS" if target_observation_defined else "NOT_TESTABLE_TARGET_SCHEMA",
                                       "valid_target_count": len(valid_targets),
                                       "source": "claim_schema_v2;typed-address-validation"},
            "intervention_identifiable": {"status": "CANDIDATE" if candidate_intervention else "NOT_TESTABLE_INTERVENTION",
                                           "source": "claim_schema_v2;not replay authorization"},
            "state_consistent": {"status": "NOT_RUN", "reason": "no case-specific coupled plan consumed by A4"},
            "execution_comparable": {"status": "NOT_RUN", "reason": "no admissible counterfactual replay"},
            "outcome_observable": {"status": "NOT_RUN", "reason": "reported harm is not a committed counterfactual observation"},
            "scanner_mapping": {
                "status": mapping_row.get("status", "MISSING"),
                "operator_types": mapping_row.get("mapped_operator_types", []),
            },
            "verdict": "NOT_TESTABLE_NOT_YET_REPLAYED",
        })
    artifact = {
        "schema_version": 1,
        "artifact": "e5-claim-testability-matrix",
        "corpus_id": "m4-frozen-20",
        "policy": "normalization and gate inventory only; no causal verdicts",
        "gate_order": ["localizable", "target_effect_defined", "intervention_identifiable",
                        "state_consistent", "execution_comparable", "outcome_observable"],
        "counts": {
            "cases": len(rows),
            "localizable_pass": sum(x["localizable"]["status"] == "PASS" for x in rows),
            "target_effect_defined": sum(x["target_effect_defined"]["status"] == "PASS" for x in rows),
            "candidate_intervention": sum(x["intervention_identifiable"]["status"] == "CANDIDATE" for x in rows),
            "admissible_replay": 0,
        },
        "cases": rows,
    }
    OUT.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")
    print(json.dumps(artifact["counts"], indent=2))


if __name__ == "__main__":
    main()

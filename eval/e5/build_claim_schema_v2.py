"""Build the auditable E5 root-cause claim schema from frozen annotations.

This is normalization only. It does not infer a causal variable, dependency
path, or intervention result when the frozen evidence does not provide one.
"""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CROSSWALK = ROOT / "eval/results/e5_rcfh/label_crosswalk.json"
ADJUDICATION = ROOT / "corpus/annotations/adjudication/e4_adjudication_completed_reviewer_c.jsonl"
OUT = ROOT / "eval/results/e5_rcfh/claim_schema_v2.json"


def load_adjudication() -> dict[str, dict]:
    result = {}
    for line in ADJUDICATION.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            result[row["case_id"]] = row
    return result


def claim_record(case: dict, adjudicated: dict | None) -> dict:
    local = case["sources"]["defihacklabs_local_corpus"]["claim"] or {}
    independent = case["sources"]["incident_explorer"]["claim"]
    root_gt = (adjudicated or {}).get("root_cause_gt", [])
    adjudication_note = (adjudicated or {}).get("adjudication", {}).get("note")
    harm = (adjudicated or {}).get("harm_spec") or {}
    objective = (adjudicated or {}).get("security_objective") or {}
    interventions = (adjudicated or {}).get("intervention_candidates", [])
    victims = harm.get("victims", [])

    return {
        "case_id": case["case_id"],
        "tx_hash": case["tx_hash"],
        "claim_status": "NORMALIZED_FROM_REVIEWER_C"
        if root_gt else "UNRESOLVED",
        "root_mechanism": {
            "ontology_labels": root_gt,
            "statement": adjudication_note,
        },
        "enabling_factors": local.get("factor_labels", []),
        "enabling_primitives": (adjudicated or {}).get("enabling_primitives", []),
        "vulnerable_boundary": {
            "security_objective_reference": objective.get("reference"),
            "security_objective_kind": objective.get("kind"),
            "causal_calls": (adjudicated or {}).get("causal_calls", []),
        },
        "causal_variable": None,
        "dependency_path": None,
        "protected_target": victims,
        "harm_definition": {
            "observation_scope": "transaction",
            "harm_spec": harm,
            "reported_loss_not_used_as_counterfactual": True,
        },
        "candidate_interventions": interventions,
        "expected_counterfactual_effect": None,
        "provenance": {
            "local_claim": local,
            "incident_explorer_claim": independent,
            "adjudication_file": str(ADJUDICATION.relative_to(ROOT)),
            "adjudication_status": (adjudicated or {}).get("adjudication", {}).get("status"),
            "label_confidence": (adjudicated or {}).get("label_confidence"),
        },
        "replay_status": "NOT_RUN",
    }


def main() -> None:
    crosswalk = json.loads(CROSSWALK.read_text())
    adjudication = load_adjudication()
    cases = [claim_record(case, adjudication.get(case["case_id"])) for case in crosswalk["cases"]]
    output = {
        "schema_version": 2,
        "artifact": "e5-root-cause-claim-schema",
        "corpus_id": "m4-frozen-20",
        "purpose": "normalize claims before causal-boundary mapping; not ground truth and not replay evidence",
        "normalization_policy": {
            "root_mechanism_source": "Reviewer-C adjudication root_cause_gt",
            "factor_labels_role": "enabling_or_candidate_factors_only",
            "missing_semantics": "null; never inferred from selector presence",
            "reported_loss_role": "external incident evidence only",
        },
        "counts": {
            "case_count": len(cases),
            "normalized_root_mechanism": sum(bool(c["root_mechanism"]["statement"]) for c in cases),
            "unresolved_root_mechanism": sum(not c["root_mechanism"]["statement"] for c in cases),
            "replay_run": 0,
        },
        "cases": cases,
    }
    OUT.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(output["counts"], sort_keys=True))


if __name__ == "__main__":
    main()

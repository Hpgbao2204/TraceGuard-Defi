"""Build a complete inventory of falsification evidence across the repo.

This command does not invent replay outcomes.  It joins the frozen 20-case
claim matrix with supplementary public-RCA probes and the existing certificates
so that unrun cases are visible rather than silently omitted.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "eval/results/e5_rcfh/all_case_falsification_inventory_v1.json"


def load(rel: str) -> dict:
    return json.loads((ROOT / rel).read_text())


def main() -> int:
    matrix = load("eval/results/e5_rcfh/claim_testability_matrix.json")
    rows = []
    for case in matrix["cases"]:
        rows.append({
            "case_id": case["case_id"],
            "corpus": "fixed20",
            "public_hypothesis": case.get("root_mechanism"),
            "mutation_executed": False,
            "falsification_status": "NOT_RUN_POLICY_FROZEN",
            "source_status": case.get("verdict"),
            "blocker": case.get("execution_comparable", {}).get("reason"),
        })

    supplements = [
        ("Dough Finance", "supplementary", "INCONCLUSIVE_COUNTERFACTUAL_REVERT_BEFORE_HARM_COMPARABILITY", "eval/results/e5_rcfh/dough_public_rca_verification_v1.json"),
        ("Bao Finance", "supplementary", "INCONCLUSIVE_COUNTERFACTUAL_REVERT_BEFORE_HARM", "eval/results/e5_rcfh/bao_public_rca_verification_v1.json"),
        ("Euler Finance", "supplementary", "DEPENDENCY_ONLY", "eval/results/e5_rcfh/euler_public_rca_status_audit_v1.json"),
        ("Harvest Finance", "supplementary", "SHAM_READY_NOT_CAUSAL", "eval/results/e5_rcfh/harvest_public_rca_status_audit_v1.json"),
        ("Indexed Finance", "supplementary", "SEAM_NOT_FROZEN", "eval/results/e5_rcfh/public_rca_case_progress_audit_v1.json"),
        ("XLoot", "supplementary", "INCONCLUSIVE_COUNTERFACTUAL_REVERT_BEFORE_HARM", "eval/results/m6_xloot_root_cause_certificate_v1.json"),
    ]
    for name, corpus, status, artifact in supplements:
        rows.append({
            "case_id": name,
            "corpus": corpus,
            "mutation_executed": True if name != "Indexed Finance" else False,
            "falsification_status": status,
            "artifact": artifact,
            "blocker": "protected harm boundary, comparable counterfactual, or exact semantic seam remains incomplete",
        })

    report = {
        "schema_version": 1,
        "scope": "all currently materialized DeFiHackLabs/public-RCA cases in this repository",
        "policy": "Unrun fixed-20 cases are shown explicitly as policy-frozen; no missing row is treated as a negative or causal result.",
        "rows": rows,
        "summary": {
            "case_count": len(rows),
            "fixed20_count": sum(r["corpus"] == "fixed20" for r in rows),
            "supplementary_count": sum(r["corpus"] == "supplementary" for r in rows),
            "mutation_materialized": sum(r["mutation_executed"] for r in rows),
            "not_run_policy_frozen": sum(r["falsification_status"] == "NOT_RUN_POLICY_FROZEN" for r in rows),
        },
        "limitations": [
            "This inventory is not a new replay and does not turn baseline-only artifacts into falsification results.",
            "The fixed-20 policy explicitly forbids altering the frozen corpus in the current checkpoint.",
            "Supplementary mutation rows retain their existing INCONCLUSIVE/DEPENDENCY_ONLY scope where the counterfactual reverted or harm was not adjudicated.",
        ],
    }
    OUT.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

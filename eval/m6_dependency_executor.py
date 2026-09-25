"""D3 dependency executor contract.

This module deliberately does not reuse the causal verdict path.  The replay
adapter is injected by a later provider-specific implementation; this layer
only validates frozen contracts and classifies observed evidence fail-closed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MATRIX = ROOT / "eval/results/m6_dependency_operator_matrix.json"

TERMINAL = {"DEPENDENCY_CONFIRMED", "DEPENDENCY_NOT_CONFIRMED", "INCONCLUSIVE"}


def classify(evidence: dict) -> dict:
    """Classify one observed real/sham run without using CAUSE semantics."""
    required = ("baseline_fidelity", "provider_frame", "callback_boundary",
                "real_intervention_application", "expected_blocking_site",
                "sham_executable", "provenance")
    missing = [key for key in required if evidence.get(key) is not True]
    if missing:
        return {"status": "INCONCLUSIVE", "reason": "missing_gate:" + ",".join(missing)}
    if evidence.get("real_reverted") is True and evidence.get("blocking_boundary_observed") is True:
        return {"status": "DEPENDENCY_CONFIRMED", "reason": "preregistered boundary blocked"}
    if evidence.get("real_executed") is True and evidence.get("blocking_boundary_observed") is False:
        return {"status": "DEPENDENCY_NOT_CONFIRMED", "reason": "exploit path remained executable"}
    return {"status": "INCONCLUSIVE", "reason": "real outcome or boundary ambiguous"}


def validate_plan(matrix: dict) -> dict:
    rows = matrix.get("cases", [])
    ready = [r for r in rows if r.get("semantic_support") == "D2_READY"]
    errors = []
    for row in ready:
        for key in ("provider_address", "exact_selector", "callback_selector",
                    "expected_boundary", "intervention_contract", "sham_control",
                    "sham_expected_behavior"):
            if not row.get(key):
                errors.append(f"{row.get('case_id')}: missing {key}")
        if not row.get("replay_authorized"):
            errors.append(f"{row.get('case_id')}: not replay-authorized")
    return {"ready_cases": len(ready), "errors": errors,
            "replay_authorized": len(ready) == 4 and not errors,
            "case_ids": [r["case_id"] for r in ready]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matrix", type=Path, default=MATRIX)
    parser.add_argument("--plan-out", type=Path,
                        default=ROOT / "eval/results/m6_dependency_execution_plan.json")
    args = parser.parse_args()
    matrix = json.loads(args.matrix.read_text(encoding="utf-8"))
    validation = validate_plan(matrix)
    plan = {"schema_version": 1, "status": "D3_EXECUTOR_CONTRACT_READY",
            "execution_performed": False, "taxonomy": sorted(TERMINAL),
            "matrix_sha256": __import__("hashlib").sha256(args.matrix.read_bytes()).hexdigest(),
            **validation}
    args.plan_out.parent.mkdir(parents=True, exist_ok=True)
    args.plan_out.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(plan, indent=2))
    return 0 if validation["replay_authorized"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

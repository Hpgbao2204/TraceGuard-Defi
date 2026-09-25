#!/usr/bin/env python3
"""Audit the depth and scope of the frozen Mure E5 verdict."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FINAL = ROOT / "eval/results/e5_rcfh/mure_erc1271_final_verdict.json"
GATES = ROOT / "eval/results/e5_rcfh/mure_erc1271_gate_ab_assessment.json"
BOUNDARY = ROOT / "eval/results/e5_rcfh/muredistribution_boundary_materialized.json"
SHAM = ROOT / "eval/results/e5_rcfh/mure_erc1271_pilot/sham.json"
CF = ROOT / "eval/results/e5_rcfh/mure_erc1271_pilot/counterfactual.json"
OUT = ROOT / "eval/results/e5_rcfh/mure_erc1271_supported_root_depth_audit.json"


def main() -> None:
    final = json.loads(FINAL.read_text())
    gates = json.loads(GATES.read_text())
    boundary = json.loads(BOUNDARY.read_text())
    sham = json.loads(SHAM.read_text())["per_tx"][28]
    cf = json.loads(CF.read_text())["per_tx"][28]

    baseline_transfer = boundary["observed_boundary"]["unauthorized_transfer_from"]
    seam = final["seam"]
    cf_enters = [e for e in cf["call_trace"] if e.get("event") == "enter"]
    transfer_after_seam = [
        e for e in cf_enters
        if e.get("to", "").lower() == baseline_transfer["callee"].lower()
        and e.get("input", "").lower().startswith(baseline_transfer["selector"])
    ]
    checks = {
        "exact_seam_match_once": seam["match_count"] == 1 and seam["application_verified"] is True,
        "baseline_committed_harm_bound": boundary["harm_observation_status"] == "COMMITTED_ERC20_TRANSFER_OBSERVED",
        "sham_preserves_baseline": all(sham[k] for k in ["status_match", "gas_match", "logs_match", "post_state_match"]),
        "counterfactual_root_reverted": cf["actual_status"] is False and cf["call_intervention"]["first_revert_depth"] == 3,
        "counterfactual_has_no_transfer_call": len(transfer_after_seam) == 0,
        "atomic_rollback_gate": gates["gate_b_state_invariant_preservation"]["status"] == "PASS_ATOMIC_ROLLBACK",
    }
    assert all(checks.values()), checks
    out = {
        "schema_version": 1,
        "artifact": "e5-mure-supported-root-depth-audit",
        "case_id": final["case_id"],
        "checks": checks,
        "claim_supported": "caller-controlled ERC-1271 validation is necessary for the observed unauthorized QUEST transfer in this historical transaction",
        "supported_verdict": "SUPPORTED_ROOT_BLOCKING",
        "scope": "single historical transaction; invalid validation result blocks the transfer path and root rollback prevents committed state",
        "not_established": [
            "source-level branch identity beyond immediate revert propagation",
            "universal root cause for every MureDistribution attack",
            "absence of alternative attack paths",
            "cross-transaction dependency",
        ],
        "residual_classification": "SUPPORTED_NECESSITY_BLOCKING_NOT_UNIVERSAL_ROOT_PROOF",
        "source_hashes": {
            "final": hashlib.sha256(FINAL.read_bytes()).hexdigest(),
            "gates": hashlib.sha256(GATES.read_bytes()).hexdigest(),
            "boundary": hashlib.sha256(BOUNDARY.read_bytes()).hexdigest(),
            "sham": hashlib.sha256(SHAM.read_bytes()).hexdigest(),
            "counterfactual": hashlib.sha256(CF.read_bytes()).hexdigest(),
        },
    }
    OUT.write_text(json.dumps(out, indent=2) + "\n")
    print(OUT)
    print(hashlib.sha256(OUT.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()

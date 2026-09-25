"""Fail-closed eligibility report for Harm-v2 counterfactual replay.

This does not run a replay.  It prevents old dependency-only artifacts from
being mistaken for a Harm-v2 causal authorization.
"""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REG = json.loads((ROOT / "eval/results/m6_harm_t1_registry_v1.json").read_text())
READY = json.loads((ROOT / "eval/results/m6_causal_readiness_matrix.json").read_text())
ADJ = json.loads((ROOT / "eval/results/m6_supplementary_reviewer_c_audit.json").read_text())
ALKIMIYA_PATCH = json.loads((ROOT / "eval/results/m6_alkimiya_patched_code_preflight_v2.json").read_text())

def main():
    reg = {x["case_id"]: x for x in REG["cases"]}
    adjudicated = {x["case_id"]: x for x in ADJ["cases"]}
    rows = []
    for case in READY["cases"]:
        cid = case["case_id"]
        boundary = reg.get(cid)
        gates = {
            "baseline_fidelity": bool(case.get("context_valid")),
            "raw_harm_measurable": adjudicated.get(cid, {}).get("harm_status") == "MEASURABLE" and boundary is not None,
            "frozen_t1_boundary": boundary is not None and boundary.get("status") == "FROZEN_ADJUDICATED",
            "intervention_application": bool(case.get("application_contract")),
            "intervention_semantic": bool(case.get("semantic_contract")),
            "execution_comparable": bool(case.get("execution_comparability")),
        }
        if cid.endswith("alkimiya-io-2025-03-28"):
            gates["root_cause_intervention_preregistered"] = ALKIMIYA_PATCH.get("status") == "READY_FOR_RPC_STATE_OVERRIDE"
            # The existing canonical result is a blocking guard result, not
            # an execution-comparable removal-style counterfactual.
            gates["execution_comparable"] = False
            reason = "arithmetic/downcast patch is frozen, but the patched branch blocks before counterfactual harm observation"
        elif cid.endswith("xlootstaking-2026-04-15"):
            gates["root_cause_intervention_preregistered"] = False
            reason = "dependency seam is frozen, but no execution-comparable root-cause intervention is frozen"
        else:
            gates["root_cause_intervention_preregistered"] = False
            reason = "no frozen T1 boundary/intervention record for this case"
        authorized = all(gates.values())
        outcome = None
        if not authorized and cid.endswith("alkimiya-io-2025-03-28"):
            outcome = "INCONCLUSIVE_EXECUTION"
        elif not authorized and cid.endswith("xlootstaking-2026-04-15"):
            outcome = "NOT_EVALUABLE"
        rows.append({"case_id": cid, "gates": gates, "causal_replay_authorized": authorized,
                     "provisional_taxonomy": outcome, "reason": None if authorized else reason})
    out = {"schema_version": 1, "policy": "harm-v2-comparability-v1",
           "replay_executed": False, "authorized_count": sum(x["causal_replay_authorized"] for x in rows),
           "cases": rows}
    p = ROOT / "eval/results/m6_harm_v2_causal_eligibility.json"
    p.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"authorized_count": out["authorized_count"], "cases": len(rows)}, indent=2))

if __name__ == "__main__": main()

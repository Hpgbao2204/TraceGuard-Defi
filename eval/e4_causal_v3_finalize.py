"""Finalize the E4 causal-v3 pilot without converting diagnostics to causality."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def read(name):
    return json.loads((ROOT / name).read_text())

def main():
    audit = read("eval/results/e4_causal_v3_inconclusive_audit.json")
    pilot = read("eval/results/e4_causal_v3_pilot.json")
    protocol = read("eval/results/e4_causal_v3_protocol_freeze.json")
    eligibility = read("eval/results/m6_harm_v2_causal_eligibility.json")
    b1 = audit["counts"]
    report = {
        "schema_version": 1,
        "protocol": "E4-CAUSAL-V3",
        "status": "PILOT_CLOSED_FAIL_CLOSED",
        "historical_artifacts_mutated": False,
        "phases": {
            "C1_inconclusive_audit": "COMPLETE",
            "C2_harm_predicate": "COMPLETE",
            "C3_capital_substitution_spec": "COMPLETE_CONTRACT_ONLY",
            "C4_sham_semantic_contract": "COMPLETE_CONTRACT_ONLY",
            "C5_blocking_revert_contract": "COMPLETE_CONTRACT_ONLY",
            "C6_pilot": "COMPLETE_NO_AUTHORIZED_CASE",
            "C7_cross_provider": "NOT_AUTHORIZED",
            "C8_admission_freeze": "FROZEN_PILOT_ADMISSION_RULES",
            "C9_family_expansion": "NOT_AUTHORIZED",
            "C10_metrics": "COMPLETE_PILOT_METRICS",
        },
        "admission_metrics": {
            "screened_frozen20": 20,
            "baseline_b1": b1.get("B1", 0),
            "baseline_b2": b1.get("B2", 0),
            "baseline_b4": b1.get("B4", 0),
            "pilot_cases": pilot["summary"]["pilot_cases"],
            "intervention_validity": 0.0,
            "execution_comparability": 0.0,
            "causal_observability": 0.0,
            "causal_verdicts": 0,
            "dependency_confirmed_diagnostics": sum(1 for x in pilot["cases"] if x["dependency_result_preserved"]),
        },
        "outcomes": {
            "CAUSE": 0,
            "NOT_NECESSARY": 0,
            "INCONCLUSIVE_EXECUTION": 0,
            "INCONCLUSIVE_OBSERVATION": 0,
            "DEPENDENCY_ONLY": 2,
            "NOT_EVALUATED": 0,
        },
        "claim_scope": "No causal necessity claim. Existing D4 records remain execution-dependency diagnostics.",
        "stop_reason": "No provider-specific capital-source substitution preserved the callback; C7 and family expansion are not authorized.",
        "input_artifacts": {
            "inconclusive_audit": "eval/results/e4_causal_v3_inconclusive_audit.json",
            "protocol_freeze": "eval/results/e4_causal_v3_protocol_freeze.json",
            "pilot": "eval/results/e4_causal_v3_pilot.json",
            "harm_eligibility": "eval/results/m6_harm_v2_causal_eligibility.json",
        },
    }
    out = ROOT / "eval/results/e4_causal_v3_final_report.json"
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": report["status"], "causal_verdicts": 0, "dependency_only": 2}, indent=2))

if __name__ == "__main__": main()

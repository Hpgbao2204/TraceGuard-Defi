"""Classify existing D4 seams against the stricter v3 substitution contract.

Existing D4 runs are dependency diagnostics.  This report intentionally does
not reinterpret them as capital-substitution counterfactuals.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES = {
    "defihacklabs-xlootstaking-2026-04-15": ROOT / "eval/results/m6_dependency_xloot_d4_result.json",
    "defihacklabs-alkimiya-io-2025-03-28": ROOT / "eval/results/m6_morpho_d4_result.json",
}

def main():
    rows = []
    for case_id, path in CASES.items():
        d = json.loads(path.read_text())
        real = d.get("real_intervention", {})
        sham = d.get("sham", {})
        rows.append({
            "case_id": case_id,
            "source_artifact": str(path.relative_to(ROOT)),
            "source_estimand": d.get("estimand"),
            "provider_seam_match": real.get("match_count") == 1,
            "application_verified": real.get("application_verified") is True,
            "callback_reached": real.get("callback_reached", 0) > 0,
            "sham_execution_preserved": sham.get("execution_preserved") is True,
            "capital_substitution_applied": False,
            "same_callback_preserved": False,
            "pilot_status": "NOT_AUTHORIZED_CAPITAL_SUBSTITUTION_NOT_APPLIED",
            "dependency_result_preserved": d.get("status") == "DEPENDENCY_CONFIRMED",
            "causal_verdict": "NOT_EVALUATED",
        })
    out = {
        "schema_version": 1,
        "protocol": "E4-CAUSAL-V3",
        "phase": "C6 pilot",
        "reinterprets_historical_d4": False,
        "cases": rows,
        "summary": {"pilot_cases": len(rows), "authorized": 0, "causal_results": 0},
    }
    p = ROOT / "eval/results/e4_causal_v3_pilot.json"
    p.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(json.dumps(out["summary"], indent=2))

if __name__ == "__main__": main()

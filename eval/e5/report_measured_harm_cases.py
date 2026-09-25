"""Summarize existing measured-harm replay evidence for E5."""
from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "eval/results/e5_rcfh/measured_harm_case_report.json"

def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main() -> None:
    dep = json.loads((ROOT / "eval/results/m6_alkimiya_paired_dependency_result.json").read_text())
    files = [
        "eval/results/m6_alkimiya_paired_dependency_result.json",
        "eval/results/e4_causal_v4/alkimiya_morpho_capital_substitution_sham.json",
        "eval/results/e4_causal_v4/alkimiya_morpho_capital_substitution_counterfactual.json",
        "eval/results/e4_causal_v4/alkimiya_slot_resolution.json",
        "eval/results/m6_xloot_FINAL_verdict.json",
        "eval/results/m6_xloot_native_harm_audit.json",
    ]
    xloot = json.loads((ROOT / "eval/results/m6_xloot_FINAL_verdict.json").read_text())
    xloot_harm = json.loads((ROOT / "eval/results/m6_xloot_native_harm_audit.json").read_text())
    result = {
        "schema_version": 1,
        "artifact": "e5-measured-harm-case-report",
        "corpus_id": "supplementary-alkimiya",
        "scope": "existing proof-bound replay evidence; no new mutation",
        "cases": [{
            "case_id": dep["case_id"],
            "claim_scope": dep["claim_scope"],
            "baseline": dep["baseline"],
            "sham": dep["sham"],
            "counterfactual": dep["mutation"],
            "verdict": "INCONCLUSIVE",
            "reason": dep["reason_code"],
            "not_cause": True,
        }, {
            "case_id": xloot["case_id"],
            "claim_scope": xloot["claim_scope"],
            "baseline": xloot_harm["baseline"],
            "eligibility": "NOT_ELIGIBLE_BASELINE_HARM_BELOW_LMIN",
            "verdict": xloot["verdict"],
            "reason": xloot["reason"],
            "not_cause": True,
        }],
        "evidence_files": [{"path": p, "sha256": digest(ROOT / p)} for p in files],
        "interpretation": "Alkimiya has measured baseline HARM but its flash-liquidity intervention reverts before paired harm observation, so it supports execution dependency only. XLoot has a measured native debit but is below the preregistered harm threshold; necessity is undefined. Neither produces a causal verdict.",
    }
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"case_count": len(result["cases"]), "baseline_harm": dep["baseline"]["harm_status"], "verdict": "INCONCLUSIVE", "reason": dep["reason_code"]}, indent=2))

if __name__ == "__main__": main()

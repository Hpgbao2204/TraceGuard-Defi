"""Summarize every measured-harm case and available intervention attempt.

This is a reporting join only. It never upgrades a diagnostic vector or an
old artifact into a new causal verdict.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evidence(path: str) -> dict:
    p = ROOT / path
    return {"path": path, "exists": p.exists(), "sha256": sha(p) if p.exists() else None}


def main() -> None:
    alk = json.loads((ROOT / "eval/results/m6_alkimiya_paired_dependency_result.json").read_text())
    alk_final = json.loads((ROOT / "eval/results/m6_alkimiya_FINAL_verdict.json").read_text())
    xloot = json.loads((ROOT / "eval/results/m6_xloot_FINAL_verdict.json").read_text())
    t0 = json.loads((ROOT / "eval/results/e5_rcfh/prior_mutation_t0_materialization.json").read_text())

    report = {
        "schema_version": 1,
        "artifact": "e5-all-measured-harm-attempts",
        "scope": "existing measured-harm evidence plus existing mutation artifacts",
        "policy": "reported loss and old baseline harm do not substitute for a committed paired mutation ledger",
        "cases": [
            {
                "case_id": "defihacklabs-alkimiya-io-2025-03-28",
                "baseline": {
                    "harm_status": alk["baseline"]["harm_status"],
                    "harm_base_units": alk["baseline"]["harm_base_units"],
                    "harm_usd": alk["baseline"]["harm_usd"],
                    "lmin_usd": alk["baseline"]["lmin_usd"],
                },
                "interventions": [
                    {
                        "name": "Morpho flash-liquidity dependency",
                        "result": alk["verdict"],
                        "reason": alk["reason_code"],
                        "scope": "dependency only; no root-cause claim",
                    },
                    {
                        "name": "arithmetic/downcast guard",
                        "result": alk_final["verdict"],
                        "reason": "patched runtime reaches SharesTooLarge guard and commits no state",
                        "scope": alk_final["claim_scope"],
                    },
                ],
                "classification": "MEASURED_HARM_WITH_TWO_SEPARATE_INTERVENTION_RESULTS",
            },
            {
                "case_id": "defihacklabs-xlootstaking-2026-04-15",
                "baseline": {
                    "harm_status": xloot["baseline_harm_status"],
                    "harm_usd": xloot["baseline_harm_usd"],
                    "lmin_usd": xloot["lmin_usd"],
                },
                "interventions": [],
                "classification": "BELOW_PREREGISTERED_HARM_THRESHOLD_NO_PAIRED_MUTATION",
            },
        ],
        "fixed20_prior_mutation_inventory": {
            "artifact": "eval/results/e5_rcfh/prior_mutation_t0_materialization.json",
            "declared_harm_cases": len(t0["cases"]),
            "cases_with_mutations": sum(bool(x["mutations"]) for x in t0["cases"]),
            "mutation_artifacts": sum(len(x["mutations"]) for x in t0["cases"]),
            "note": "ERC20-only diagnostic vectors; fidelity failures and missing native ledger prevent causal comparison",
        },
        "evidence_files": [
            evidence("eval/results/m6_alkimiya_paired_dependency_result.json"),
            evidence("eval/results/m6_alkimiya_FINAL_verdict.json"),
            evidence("eval/results/m6_xloot_FINAL_verdict.json"),
            evidence("eval/results/e5_rcfh/prior_mutation_t0_materialization.json"),
        ],
    }
    out = ROOT / "eval/results/e5_rcfh/all_measured_harm_attempts.json"
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"output": str(out), "cases": len(report["cases"]), "status": "WRITTEN"}, indent=2))


if __name__ == "__main__":
    main()

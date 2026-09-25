"""Generate the E5-13 metrics ledger from bounded phase artifacts."""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "eval/results/e5_rcfh"


def main() -> None:
    status = json.loads((OUT / "phase_status.json").read_text())
    cross = json.loads((OUT / "label_crosswalk.json").read_text())
    mapping = json.loads((OUT / "claim_mapping_v1.json").read_text())
    seam = json.loads((OUT / "seam_scan_summary.json").read_text())
    tier1 = status["tier1"]
    result = {
        "schema_version": 1,
        "artifact": "e5-metrics",
        "corpus_id": "m4-frozen-20",
        "corpus_integrity": {"case_count": len(cross["cases"]), "all_fixed20": len(cross["cases"]) == 20},
        "observability": {"canonical_runs": len(cross["cases"]), "seam_groups": seam["total_groups"], "seam_occurrences": seam["total_occurrences"], "claim_mapping_coverage": mapping["coverage"], "interpretation": "scanner coverage only; not a falsifiability estimate"},
        "intervention": {"admitted": 0, "same_kind_sham_pass": 0, "comparable_counterfactuals": 0},
        "necessity_outcomes": {"SUPPORTED": 0, "NOT_SUPPORTED": 0, "PARTIAL_EFFECT": 0, "NOT_TESTABLE": sum(x["status"] == "NOT_TESTABLE" for x in tier1), "CLAIM_NOT_LOCALIZABLE": sum(x["status"] == "CLAIM_NOT_LOCALIZABLE" for x in tier1)},
        "calibration": {"status": "NOT_RUN", "tested": 0, "false_necessity_rate": None, "reason": "no authorized seam replay"},
        "patch_regression": {"status": "NOT_RUN", "tested": 0, "false_positive_rate": None, "reason": "no necessary mechanism identified"},
        "gold_subset": {"status": "NOT_RUN", "tested": 0, "reason": "no E5 supported/refuted outcome"},
        "tier_b": {"status": "NOT_OPENED", "reason": "Tier A admission gates incomplete"},
        "interpretation": "Metrics describe evidence coverage and blocked phases; they do not support a causal efficacy claim.",
    }
    (OUT / "metrics.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result["necessity_outcomes"], indent=2))


if __name__ == "__main__": main()

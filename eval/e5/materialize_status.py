"""Materialize bounded E5 phase status without inventing replay evidence."""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "eval/results/e5_rcfh"


def main() -> None:
    cross = json.loads((OUT / "label_crosswalk.json").read_text())
    mapping = json.loads((OUT / "claim_mapping_v1.json").read_text())
    seam = json.loads((OUT / "seam_scan_summary.json").read_text())
    tier1 = []
    tier2 = []
    for row in mapping["cases"]:
        reason = "CLAIM_NOT_LOCALIZABLE" if row["status"] == "CLAIM_NOT_LOCALIZABLE" else "REPLAY_NOT_AUTHORIZED_PHASE2_MAPPING_REVIEW_PENDING"
        tier1.append({"case_id": row["case_id"], "status": "CLAIM_NOT_LOCALIZABLE" if row["status"] == "CLAIM_NOT_LOCALIZABLE" else "NOT_TESTABLE", "reason": reason, "same_kind_sham_pass": False, "replay_executed": False})
        tier2.append({"case_id": row["case_id"], "status": "NOT_TESTABLE", "reason": "TIER1_REPLAY_NOT_EXECUTED", "profile": None})
    (OUT / "tier1").mkdir(exist_ok=True)
    (OUT / "tier2").mkdir(exist_ok=True)
    for row in tier1:
        (OUT / "tier1" / f"{row['case_id']}.json").write_text(json.dumps(row, indent=2) + "\n")
    for row in tier2:
        (OUT / "tier2" / f"{row['case_id']}.json").write_text(json.dumps(row, indent=2) + "\n")
    near = ROOT / "eval/results/runs/p7-near-negative-20260912-r1/cohort_manifest.json"
    near_count = 0
    if near.exists():
        near_count = len(json.loads(near.read_text()).get("near_negative_test", []))
    result = {
        "schema_version": 1,
        "artifact": "e5-phase-status",
        "corpus_id": "m4-frozen-20",
        "phase0": {"status": "PARTIAL", "local_claim_coverage": "20/20", "independent_source_coverage": "0/20", "cross_source_agreement": "NOT_ESTIMABLE", "crosswalk_cases": len(cross["cases"])},
        "phase1": {"status": "COMPLETE", "seam_groups": seam["total_groups"], "occurrences": seam["total_occurrences"]},
        "phase2": mapping["coverage"],
        "phase3": {"status": "NOT_RUN", "reason": "Gate 2 below threshold; no reviewed claim mapping or replay authorization"},
        "phase4": {"status": "NOT_RUN", "reason": "Tier 1 replay not executed"},
        "phase5": {"status": "NOT_RUN", "near_negative_available": near_count, "false_necessity_rate": None, "reason": "No seam replay authorized"},
        "phase6": {"status": "NOT_RUN", "reason": "No necessary mechanism identified"},
        "phase7": {"status": "NOT_OPENED", "reason": "Tier A gates incomplete"},
        "phase8": {"status": "NOT_RUN", "reason": "No supported/alternative verdicts to adjudicate"},
        "phase9": {"status": "OUT_OF_SCOPE", "reason": "Detector training is future work"},
        "tier1": tier1,
        "tier2": tier2,
        "verdict_policy": "No SUPPORTED, NOT_SUPPORTED, or ALTERNATIVE_CAUSE verdict is emitted without same-kind sham and comparable replay.",
    }
    (OUT / "phase_status.json").write_text(json.dumps(result, indent=2) + "\n")
    blocked = {
        "schema_version": 1,
        "corpus_id": "m4-frozen-20",
        "status": "NOT_RUN",
        "tested": 0,
        "reason": "no reviewed intervention seam or replay authorization",
    }
    (OUT / "false_necessity_calibration.json").write_text(json.dumps({**blocked, "false_necessity_rate": None, "near_negative_available": near_count}, indent=2) + "\n")
    (OUT / "patch_regression.json").write_text(json.dumps({**blocked, "false_positive_rate": None}, indent=2) + "\n")
    (OUT / "gold_subset_adjudication.json").write_text(json.dumps({**blocked, "manual_cases": []}, indent=2) + "\n")
    (OUT / "tier_b_gate.json").write_text(json.dumps({"schema_version": 1, "corpus_id": "m4-frozen-20", "status": "NOT_OPENED", "reason": "Tier A gates incomplete"}, indent=2) + "\n")
    print(json.dumps({"phase1": result["phase1"], "phase2": result["phase2"], "phase3": result["phase3"]}, indent=2))


if __name__ == "__main__": main()

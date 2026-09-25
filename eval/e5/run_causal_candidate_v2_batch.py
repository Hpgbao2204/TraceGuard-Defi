"""V2 batch runner: runs both dev and held-out manifests, scores, and compares with v1.

This is the top-level orchestrator for the v2 causal candidate ranking
pipeline.  It produces a comparison report between v1 and v2.
"""
from __future__ import annotations

import json
from pathlib import Path

from eval.e5.run_causal_candidate_v2 import run as run_v2
from eval.e5.score_causal_candidate_v2 import score as score_v2

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "eval/results/e5_rcfh"


def main() -> None:
    # Load manifests
    dev_manifest = RESULTS / "causal_candidate_dev_manifest_v2.json"
    heldout_manifest = RESULTS / "causal_candidate_heldout_manifest_v2.json"
    refs_path = RESULTS / "causal_candidate_hidden_references_v2.json"
    refs = json.loads(refs_path.read_text())

    # Run v2 on both splits
    dev_result = run_v2(dev_manifest)
    heldout_result = run_v2(heldout_manifest)

    # Score both
    dev_scores = score_v2(dev_result, refs)
    heldout_scores = score_v2(heldout_result, refs)

    # Save intermediate results
    (RESULTS / "causal_candidate_v2_dev_result.json").write_text(
        json.dumps(dev_result, indent=2) + "\n")
    (RESULTS / "causal_candidate_v2_heldout_result.json").write_text(
        json.dumps(heldout_result, indent=2) + "\n")
    (RESULTS / "causal_candidate_v2_dev_scores.json").write_text(
        json.dumps(dev_scores, indent=2) + "\n")
    (RESULTS / "causal_candidate_v2_heldout_scores.json").write_text(
        json.dumps(heldout_scores, indent=2) + "\n")

    # Load v1 for comparison
    v1_path = RESULTS / "causal_candidate_pilot_v1.json"
    v1 = json.loads(v1_path.read_text())
    v1_by_case = {c["case_id"]: c for c in v1["cases"]}

    # Build comparison
    all_v2_cases = {c["case_id"]: c for c in dev_result["cases"] + heldout_result["cases"]}
    all_v2_scores = {c["case_id"]: c for c in dev_scores["case_scores"] + heldout_scores["case_scores"]}

    comparison_rows = []
    for case_id in sorted(set(v1_by_case) | set(all_v2_cases)):
        v1c = v1_by_case.get(case_id, {})
        v2c = all_v2_cases.get(case_id, {})
        v2s = all_v2_scores.get(case_id, {})

        row = {
            "case_id": case_id,
            "v1_status": v1c.get("status", "MISSING"),
            "v2_status": v2c.get("status", "MISSING"),
            "v1_candidate_count": v1c.get("candidate_count"),
            "v2_candidate_count": v2c.get("candidate_count"),
            "v1_reduction": v1c.get("candidate_reduction", 0.0),
            "v2_reduction": v2c.get("reduction_ratio", 0.0),
            "v1_top1": v1c.get("top1_hit"),
            "v2_top1": v2s.get("top1_hit"),
            "v1_top3": v1c.get("top3_hit"),
            "v2_top3": v2s.get("top3_hit"),
            "v1_top5": v1c.get("top5_hit"),
            "v2_top5": v2s.get("top5_hit"),
        }

        # VETH boundary check
        v1_veth = v1c.get("veth_boundary_check")
        v2_veth = v2c.get("veth_boundary_check")
        if v1_veth or v2_veth:
            row["veth_trace45_above_trace17_v1"] = v1_veth.get("trace45_above_trace17") if v1_veth else None
            row["veth_trace45_above_trace17_v2"] = v2_veth.get("trace45_above_trace17") if v2_veth else None

        comparison_rows.append(row)

    # Aggregate stats
    v2_observable_scored = [s for s in all_v2_scores.values() if s.get("status") == "SCORED"]
    v2_top1 = sum(s.get("top1_hit", False) for s in v2_observable_scored)
    v2_top3 = sum(s.get("top3_hit", False) for s in v2_observable_scored)
    v2_top5 = sum(s.get("top5_hit", False) for s in v2_observable_scored)
    v2_total = len(v2_observable_scored)

    # Invariant checks
    invariants = {
        "onyxdao_not_observable": all_v2_cases.get("defihacklabs-onyxdao-2024-09-26", {}).get("status") == "NOT_OBSERVABLE",
        "no_auto_causal_verdict": all(
            c.get("status") in ("REVIEW_REQUIRED", "NOT_OBSERVABLE", "MISSING")
            for c in all_v2_cases.values()
        ),
        "veth_trace45_above_trace17": (
            all_v2_cases.get("defihacklabs-veth-2024-11-14", {})
            .get("veth_boundary_check", {})
            .get("trace45_above_trace17", False)
        ),
    }

    comparison = {
        "schema_version": "e5-causal-candidate-v2-comparison",
        "scope": "v1 vs v2 comparison across all 5 pilot cases",
        "v1_summary": v1.get("frozen_summary", v1.get("summary", {})),
        "v2_summary": {
            "top1": f"{v2_top1}/{v2_total}",
            "top3": f"{v2_top3}/{v2_total}",
            "top5": f"{v2_top5}/{v2_total}",
            "onyxdao": "NOT_OBSERVABLE",
        },
        "per_case_comparison": comparison_rows,
        "invariant_checks": invariants,
        "all_invariants_pass": all(invariants.values()),
        "interpretation": "v2 applies 5-filter pipeline with blind scoring. Ranking improvements come from temporal direction, caller/callee dedup, and semantic compatibility filters. Call-frame lineage requires trace data (currently skipped). No candidate is promoted to CAUSE.",
    }

    out_path = RESULTS / "causal_candidate_v2_comparison.json"
    out_path.write_text(json.dumps(comparison, indent=2) + "\n")

    print("=== V2 Comparison ===")
    print(json.dumps(comparison["v2_summary"], indent=2))
    print(f"\nInvariants: {'ALL PASS' if comparison['all_invariants_pass'] else 'SOME FAIL'}")
    for k, v in invariants.items():
        print(f"  {k}: {'✓' if v else '✗'}")
    print("\nPer-case reduction:")
    for row in comparison_rows:
        status = row["v2_status"]
        if status == "NOT_OBSERVABLE":
            print(f"  {row['case_id']}: NOT_OBSERVABLE")
        else:
            print(f"  {row['case_id']}: {row['v1_candidate_count']} → {row['v2_candidate_count']} "
                  f"(reduction {row['v2_reduction']:.1%})")


if __name__ == "__main__":
    main()

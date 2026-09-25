"""Separate scorer for v2 causal candidate ranking.

This script reads the runner's output (which has NO reference information)
and a separate hidden reference file, then computes Top-k metrics.

This separation guarantees zero information flow from reference -> ranking.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def score(runner_output: dict, references: dict) -> dict:
    """Score runner output against hidden references."""
    ref_map = references.get("references", {})
    case_scores = []

    for case in runner_output.get("cases", []):
        case_id = case["case_id"]
        refs = ref_map.get(case_id, [])

        if case.get("status") == "NOT_OBSERVABLE":
            case_scores.append({
                "case_id": case_id,
                "status": "NOT_OBSERVABLE",
                "reason": case.get("reason"),
                "top1_hit": False, "top3_hit": False, "top5_hit": False,
            })
            continue

        if not refs:
            case_scores.append({
                "case_id": case_id,
                "status": "NO_REFERENCE",
                "top1_hit": False, "top3_hit": False, "top5_hit": False,
            })
            continue

        ranked = case.get("ranked_candidates", [])
        ref_keys = {(r.get("semantic"), r.get("trace_index")) for r in refs}

        positions = []
        for i, c in enumerate(ranked):
            key = (c.get("semantic"), c.get("trace_index"))
            if key in ref_keys:
                positions.append(i + 1)

        case_scores.append({
            "case_id": case_id,
            "status": "SCORED",
            "candidate_count": case.get("candidate_count", 0),
            "initial_node_count": case.get("initial_node_count", 0),
            "reduction_ratio": case.get("reduction_ratio", 0.0),
            "reference_positions": positions,
            "top1_hit": any(p <= 1 for p in positions),
            "top3_hit": any(p <= 3 for p in positions),
            "top5_hit": any(p <= 5 for p in positions),
            "veth_boundary_check": case.get("veth_boundary_check"),
        })

    observable_scored = [c for c in case_scores if c["status"] == "SCORED"]
    return {
        "schema_version": "e5-causal-candidate-score-v2",
        "scope": "blind scoring against hidden references",
        "split": runner_output.get("split", "unknown"),
        "case_scores": case_scores,
        "summary": {
            "case_count": len(case_scores),
            "observable_scored": len(observable_scored),
            "not_observable": sum(1 for c in case_scores if c["status"] == "NOT_OBSERVABLE"),
            "top1_hits": sum(c["top1_hit"] for c in observable_scored),
            "top3_hits": sum(c["top3_hit"] for c in observable_scored),
            "top5_hits": sum(c["top5_hit"] for c in observable_scored),
            "top1_rate": f"{sum(c['top1_hit'] for c in observable_scored)}/{len(observable_scored)}" if observable_scored else "N/A",
            "top3_rate": f"{sum(c['top3_hit'] for c in observable_scored)}/{len(observable_scored)}" if observable_scored else "N/A",
            "top5_rate": f"{sum(c['top5_hit'] for c in observable_scored)}/{len(observable_scored)}" if observable_scored else "N/A",
        },
        "causal_verdict_count": 0,
        "interpretation": "Top-k measures ranking quality only; no candidate is promoted to a causal verdict.",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("runner_output", type=Path, help="Output JSON from run_causal_candidate_v2")
    ap.add_argument("hidden_refs", type=Path, help="Hidden references JSON")
    ap.add_argument("-o", "--output", type=Path, required=True)
    args = ap.parse_args()

    runner = json.loads(args.runner_output.read_text())
    refs = json.loads(args.hidden_refs.read_text())
    result = score(runner, refs)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()

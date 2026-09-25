"""Blind candidate runner using raw authenticated B2 call traces."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from eval.e5.candidate_filter import apply_filter_pipeline
from eval.e5.trace_candidate_extractor import extract_b2_call_nodes


def _rank(nodes, harm, veth_check=False):
    harm_index = harm.get("trace_index")
    result = apply_filter_pipeline(nodes, harm_trace_index=harm_index,
                                   harm_semantic=harm.get("semantic"),
                                   call_trace=None, telemetry_edges=None)
    ranked = []
    for n in result["candidates"]:
        idx = n.get("trace_index")
        distance = abs(idx - harm_index) if isinstance(idx, int) and isinstance(harm_index, int) else 10**9
        score = max(0, 100 - min(distance, 100))
        if n.get("type") in {"auth_check", "oracle_read", "arithmetic", "accounting_conversion"}:
            score += 15
        ranked.append({**n, "score": score, "status": "REVIEW_REQUIRED"})
    ranked.sort(key=lambda x: (-x["score"], x["trace_index"], x["id"]))
    boundary = None
    if veth_check:
        p45 = next((i + 1 for i, n in enumerate(ranked) if n["trace_index"] == 45), None)
        p17 = next((i + 1 for i, n in enumerate(ranked) if n["trace_index"] == 17), None)
        boundary = {"trace45_rank": p45, "trace17_rank": p17,
                    "trace45_above_trace17": p45 is not None and p17 is not None and p45 < p17}
    return {"ranked_candidates": ranked[:10], "candidate_count": len(ranked),
            "initial_node_count": len(nodes), "reduction_ratio": result["reduction_ratio"],
            "pipeline_summary": result["pipeline"], "veth_boundary_check": boundary}


def run(manifest_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_text())
    root = manifest_path.parent.parent.parent.parent
    cases = []
    for spec in manifest["cases"]:
        harm = spec.get("harm_node")
        if not harm:
            cases.append({"case_id": spec["case_id"], "status": "NOT_OBSERVABLE", "reason": "harm node missing"})
            continue
        trace_path = root / spec["b2_replay"]
        nodes = extract_b2_call_nodes(trace_path) if trace_path.exists() else []
        if not nodes:
            cases.append({"case_id": spec["case_id"], "status": "NOT_OBSERVABLE", "reason": "no authenticated B2 call trace"})
            continue
        ranking = _rank(nodes, harm, spec.get("veth_trace45_vs_trace17", False))
        cases.append({"case_id": spec["case_id"], "status": "REVIEW_REQUIRED", "harm_node": harm, **ranking,
                      "limitations": ["CALL/STATICCALL extraction only", "no hidden reference access", "no replay or causal verdict"]})
    return {"schema_version": "e5-causal-candidate-v3", "scope": "blind raw-B2 trace candidate extraction", "status": "DIAGNOSTIC_ONLY", "split": manifest.get("split"), "cases": cases}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("manifest", type=Path); ap.add_argument("-o", "--output", type=Path, required=True)
    args = ap.parse_args(); args.output.write_text(json.dumps(run(args.manifest), indent=2) + "\n")


if __name__ == "__main__":
    main()

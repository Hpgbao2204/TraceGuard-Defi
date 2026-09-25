"""V2 blind causal-candidate ranking runner.

Unlike v1, this runner NEVER sees validated_references.  It consumes
seam groups, applies the 5-filter pipeline, builds a graph-aware ranking,
and outputs candidates.  Scoring is done by a separate script.

Candidate status is always REVIEW_REQUIRED or NOT_OBSERVABLE.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from eval.e5.candidate_filter import apply_filter_pipeline


def _case_nodes(seam_path: Path, extra: list[dict]) -> list[dict]:
    data = json.loads(seam_path.read_text())
    nodes = []
    for group in data.get("seam_groups", []):
        for occ in group.get("occurrences", []):
            nodes.append({
                "id": f"{group['group_id']}@{occ.get('trace_index')}",
                "group_id": group["group_id"],
                "trace_index": occ.get("trace_index"),
                "semantic": group.get("semantic", group.get("type")),
                "type": group.get("type"),
                "caller": occ.get("caller"),
                "callee": occ.get("callee"),
                "depth": occ.get("depth"),
                "source": str(seam_path),
                "provenance": "scanner_seam_occurrence",
            })
    for item in extra:
        node = dict(item)
        node.setdefault("provenance", "trace_boundary_evidence")
        node.setdefault("source", "manifest")
        nodes.append(node)
    return nodes


def _rank_with_filters(
    nodes: list[dict],
    harm: dict,
    *,
    veth_check: bool = False,
) -> dict:
    """Apply filter pipeline, then rank survivors by graph-aware score."""
    harm_index = harm.get("trace_index")
    harm_semantic = harm.get("semantic")

    # Apply the 5-filter pipeline
    pipeline_result = apply_filter_pipeline(
        nodes,
        harm_trace_index=harm_index,
        harm_semantic=harm_semantic,
        call_trace=None,  # Will be populated when trace data is available
        telemetry_edges=None,
    )

    filtered = pipeline_result["candidates"]

    # Rank survivors: type bonus + proximity to harm (before only)
    ranked = []
    for n in filtered:
        idx = n.get("trace_index")
        if isinstance(idx, int) and isinstance(harm_index, int) and idx < harm_index:
            distance = harm_index - idx
        else:
            distance = 10**9

        score = 0
        # Type-based semantic relevance
        if n.get("type") in {"auth_check", "accounting_conversion", "arithmetic"}:
            score += 15
        elif n.get("type") in {"amm_reserve_read", "oracle_read"}:
            score += 10
        elif n.get("type") in {"enabling_path", "mint", "balance_update"}:
            score += 5

        # Proximity bonus (inversely proportional to distance)
        score += max(0, 100 - min(distance, 100))

        # Telemetry boost
        if n.get("telemetry_status") == "DATAFLOW_CONNECTED":
            score += 20

        ranked.append({**n, "score": score, "status": "REVIEW_REQUIRED"})

    ranked.sort(key=lambda x: (
        -x["score"],
        x["trace_index"] if isinstance(x["trace_index"], int) else 10**9,
        x["id"],
    ))

    # VETH boundary check
    veth_order = None
    if veth_check:
        p45 = next((i + 1 for i, n in enumerate(ranked) if n.get("trace_index") == 45), None)
        p17 = next((i + 1 for i, n in enumerate(ranked) if n.get("trace_index") == 17), None)
        veth_order = {
            "trace45_rank": p45, "trace17_rank": p17,
            "trace45_above_trace17": p45 is not None and p17 is not None and p45 < p17,
        }

    return {
        "ranked_candidates": ranked[:10],
        "candidate_count": len(ranked),
        "pipeline_summary": pipeline_result["pipeline"],
        "reduction_ratio": pipeline_result["reduction_ratio"],
        "initial_node_count": pipeline_result["initial_count"],
        "veth_boundary_check": veth_order,
    }


def run(manifest_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_text())
    cases = []
    for spec in manifest["cases"]:
        repo_root = manifest_path.parent.parent.parent.parent
        seam_path = (repo_root / spec["seam_groups"]).resolve()
        if not seam_path.exists():
            cases.append({
                "case_id": spec["case_id"],
                "status": "NOT_OBSERVABLE",
                "reason": "missing seam artifact",
            })
            continue

        harm = spec.get("harm_node")
        if not harm:
            cases.append({
                "case_id": spec["case_id"],
                "status": "NOT_OBSERVABLE",
                "reason": "harm node missing",
            })
            continue

        nodes = _case_nodes(seam_path, spec.get("evidence_nodes", []))
        if not nodes:
            cases.append({
                "case_id": spec["case_id"],
                "status": "NOT_OBSERVABLE",
                "reason": "no grounded nodes",
            })
            continue

        ranking = _rank_with_filters(
            nodes, harm,
            veth_check=spec.get("veth_trace45_vs_trace17", False),
        )

        cases.append({
            "case_id": spec["case_id"],
            "status": "REVIEW_REQUIRED",
            "harm_node": harm,
            "initial_node_count": ranking["initial_node_count"],
            "candidate_count": ranking["candidate_count"],
            "reduction_ratio": ranking["reduction_ratio"],
            "pipeline_summary": ranking["pipeline_summary"],
            "veth_boundary_check": ranking["veth_boundary_check"],
            "ranked_candidates": ranking["ranked_candidates"],
            "limitations": [
                "no replay or causal verdict",
                "no validated_references in runner (blind evaluation)",
                "call-frame lineage filter requires trace data (currently skipped)",
            ],
        })

    observable = [c for c in cases if c.get("status") == "REVIEW_REQUIRED"]
    return {
        "schema_version": "e5-causal-candidate-v2",
        "scope": "blind runner: filter pipeline -> graph-aware ranking -> no reference access",
        "status": "DIAGNOSTIC_ONLY",
        "split": manifest.get("split", "unknown"),
        "cases": cases,
        "summary": {
            "case_count": len(cases),
            "observable_case_count": len(observable),
            "not_observable_case_count": len(cases) - len(observable),
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest", type=Path)
    ap.add_argument("-o", "--output", type=Path, required=True)
    args = ap.parse_args()
    result = run(args.manifest)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()

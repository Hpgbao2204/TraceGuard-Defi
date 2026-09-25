"""Run the analyst-bound causal-candidate ranking pilot.

This is deliberately not a causal verdict runner.  It consumes seam groups,
adds explicitly documented analyst boundary nodes, builds a small trace-time
candidate graph, and reports ranking/coverage metrics.  Candidate status is
always REVIEW_REQUIRED or NOT_OBSERVABLE.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


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
                "source": str(seam_path),
                "provenance": "scanner_seam_occurrence",
            })
    for item in extra:
        node = dict(item)
        node.setdefault("provenance", "trace_boundary_evidence")
        node.setdefault("source", "manifest")
        nodes.append(node)
    return nodes


def _rank(nodes: list[dict], harm: dict, refs: list[dict]) -> list[dict]:
    harm_index = harm.get("trace_index")
    ranked = []
    for n in nodes:
        idx = n.get("trace_index")
        distance = abs(idx - harm_index) if isinstance(idx, int) and isinstance(harm_index, int) else 10**9
        score = 0
        if n.get("type") in {"auth_check", "accounting_conversion", "amm_reserve_read", "arithmetic", "oracle_read"}:
            score += 10
        score += max(0, 100 - min(distance, 100))
        ranked.append({**n, "score": score, "status": "REVIEW_REQUIRED"})
    return sorted(ranked, key=lambda x: (-x["score"], x["trace_index"] if isinstance(x["trace_index"], int) else 10**9, x["id"]))


def run(manifest_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_text())
    cases = []
    for spec in manifest["cases"]:
        # Manifest lives at <repo>/eval/results/e5_rcfh; paths are repo-relative.
        repo_root = manifest_path.parent.parent.parent.parent
        seam_path = (repo_root / spec["seam_groups"]).resolve()
        if not seam_path.exists():
            cases.append({"case_id": spec["case_id"], "status": "NOT_OBSERVABLE", "reason": "missing seam artifact"})
            continue
        nodes = _case_nodes(seam_path, spec.get("evidence_nodes", []))
        harm = spec.get("harm_node")
        refs = spec.get("validated_references", [])
        if not harm or not nodes:
            cases.append({"case_id": spec["case_id"], "status": "NOT_OBSERVABLE", "reason": "harm node or grounded nodes missing"})
            continue
        ranked = _rank(nodes, harm, refs)
        ref_ids = {(r.get("semantic"), r.get("trace_index")) for r in refs}
        positions = [i + 1 for i, n in enumerate(ranked) if (n.get("semantic"), n.get("trace_index")) in ref_ids]
        candidate_count = len(ranked)
        veth_order = None
        if spec.get("veth_trace45_vs_trace17"):
            p45 = next((i + 1 for i, n in enumerate(ranked) if n.get("trace_index") == 45), None)
            p17 = next((i + 1 for i, n in enumerate(ranked) if n.get("trace_index") == 17), None)
            veth_order = {"trace45_rank": p45, "trace17_rank": p17, "trace45_above_trace17": p45 is not None and p17 is not None and p45 < p17}
        cases.append({
            "case_id": spec["case_id"],
            "status": "REVIEW_REQUIRED",
            "harm_node": harm,
            "graph_nodes": len(nodes),
            "candidate_count": candidate_count,
            "candidate_reduction": round(1 - candidate_count / len(nodes), 6) if nodes else None,
            "validated_reference_positions": positions,
            "top1_hit": any(p <= 1 for p in positions),
            "top3_hit": any(p <= 3 for p in positions),
            "top5_hit": any(p <= 5 for p in positions),
            "veth_boundary_check": veth_order,
            "ranked_candidates": ranked[:10],
            "limitations": ["seam occurrences are not full EVM SSA/dataflow", "harm node and hidden references are analyst supplied for scoring only", "no replay or causal verdict"],
        })
    observable = [c for c in cases if c.get("status") == "REVIEW_REQUIRED"]
    return {
        "schema_version": "e5-causal-candidate-pilot-v1",
        "scope": "analyst-bound harm node -> seam graph -> backward candidate ranking",
        "status": "DIAGNOSTIC_ONLY",
        "cases": cases,
        "summary": {
            "case_count": len(cases),
            "observable_case_count": len(observable),
            "not_observable_case_count": len(cases) - len(observable),
            "top1_hits": sum(c.get("top1_hit", False) for c in observable),
            "top3_hits": sum(c.get("top3_hit", False) for c in observable),
            "top5_hits": sum(c.get("top5_hit", False) for c in observable),
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest", type=Path)
    ap.add_argument("-o", "--output", type=Path, required=True)
    args = ap.parse_args()
    args.output.write_text(json.dumps(run(args.manifest), indent=2) + "\n")


if __name__ == "__main__":
    main()

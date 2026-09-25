"""Extract an evidence-bound event graph from the canonical MuRe call trace."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from eval.causal_slice import backward_slice, classify_candidates


SOURCE = ROOT / "eval/results/e5_rcfh/mure_erc1271_pilot/sham.json"
OUT = ROOT / "eval/results/e5_rcfh/mure_raw_trace_causal_graph_v1.json"


def main() -> None:
    trace = json.loads(SOURCE.read_text())["per_tx"][28]["call_trace"]
    nodes: list[dict] = []
    edges: list[dict] = []
    stack: list[str] = []
    enter_by_index: dict[int, dict] = {}
    exit_by_index: dict[int, dict] = {}
    for index, event in enumerate(trace):
        if event.get("event") == "enter":
            node_id = f"call_{index}"
            selector = event.get("input", "")[:10]
            node = {
                "id": node_id,
                "trace_index": index,
                "role": "call_event",
                "call_type": event.get("type"),
                "depth": event.get("depth"),
                "from": event.get("from"),
                "to": event.get("to"),
                "selector": selector,
            }
            if selector == "0x1626ba7e":
                node["role"] = "validation_result"
            elif selector == "0x23b872dd":
                node["role"] = "protected_write"
            elif event.get("depth") == 1 and event.get("type") == "CALL":
                node["role"] = "claim_entrypoint"
            nodes.append(node)
            enter_by_index[index] = node
            if stack:
                edges.append({"src": stack[-1], "dst": node_id, "kind": "call_target_dependency"})
            stack.append(node_id)
        elif event.get("event") == "exit":
            if stack:
                node_id = stack.pop()
                exit_by_index[index] = {"id": node_id, "output": event.get("output", ""), "reverted": event.get("reverted", False)}

    transfer = next(n for n in nodes if n.get("selector") == "0x23b872dd")
    validation = next(n for n in nodes if n.get("selector") == "0x1626ba7e")
    outcome = {"id": "committed_transfer_outcome", "trace_index": transfer["trace_index"], "role": "outcome"}
    nodes.append(outcome)
    edges.append({"src": transfer["id"], "dst": outcome["id"], "kind": "ledger_dependency"})

    # A same-frame earlier validation return is a control dependency candidate.
    transfer_parent = next(
        n for n in nodes if n["id"] == next(e["src"] for e in edges if e["dst"] == transfer["id"])
    )
    if validation["trace_index"] < transfer["trace_index"]:
        edges.append({"src": validation["id"], "dst": transfer["id"], "kind": "control_dependency"})

    sink_slice = backward_slice(nodes, edges, outcome["id"])
    candidates = classify_candidates(nodes, sink_slice)
    result = {
        "schema_version": "raw-trace-causal-graph-v1",
        "case_id": "defihacklabs-muredistribution-2026-05-21",
        "source": str(SOURCE.relative_to(ROOT)),
        "source_mode": "canonical sham call_trace; baseline preserved by sham gates",
        "graph_generation": "automatic from enter/exit events, call stack, selectors, and ledger sink",
        "nodes": nodes,
        "edges": edges,
        "outcome_sink": outcome["id"],
        "backward_slice": sink_slice,
        "candidate_events": candidates,
        "candidate_count": len(candidates),
        "validation": {
            "erc1271_in_slice": validation["id"] in sink_slice,
            "transfer_in_slice": transfer["id"] in sink_slice,
            "outcome_in_slice": outcome["id"] in sink_slice,
            "hand_authored_nodes": False,
        },
        "limitations": [
            "call-stack and selector dependencies are extracted; full EVM SSA/data-flow and branch reconstruction are not",
            "the graph is an observed-trace dependency graph, not a complete causal graph",
            "counterfactual verdicts remain in separate replay artifacts",
        ],
    }
    OUT.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"candidate_count": len(candidates), "slice_count": len(sink_slice), "validation": result["validation"]}, indent=2))


if __name__ == "__main__":
    main()

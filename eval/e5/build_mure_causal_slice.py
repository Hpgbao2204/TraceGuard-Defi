"""Build MuRe's bounded evidence graph and compute its backward slice."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from eval.causal_slice import backward_slice, classify_candidates


OUT = ROOT / "eval/results/e5_rcfh/mure_causal_slice_v1.json"


def main() -> None:
    nodes = [
        {"id": "input_distribution_source", "trace_index": 3, "role": "attacker_controlled_input"},
        {"id": "input_signer", "trace_index": 3, "role": "attacker_controlled_input"},
        {"id": "erc1271_magic_return", "trace_index": 18, "role": "validation_result"},
        {"id": "authorization_branch", "trace_index": 19, "role": "control_dependency"},
        {"id": "quest_transfer_from", "trace_index": 20, "role": "protected_write"},
        {"id": "committed_transfer_outcome", "log_index": 0, "role": "outcome"},
    ]
    edges = [
        {"src": "input_distribution_source", "dst": "erc1271_magic_return", "kind": "data_dependency"},
        {"src": "input_signer", "dst": "erc1271_magic_return", "kind": "call_target_dependency"},
        {"src": "erc1271_magic_return", "dst": "authorization_branch", "kind": "call_return_dependency"},
        {"src": "authorization_branch", "dst": "quest_transfer_from", "kind": "control_dependency"},
        {"src": "quest_transfer_from", "dst": "committed_transfer_outcome", "kind": "ledger_dependency"},
    ]
    sink = "committed_transfer_outcome"
    sliced = backward_slice(nodes, edges, sink)
    candidates = classify_candidates(nodes, sliced)
    result = {
        "schema_version": "causal-slice-v1",
        "case_id": "defihacklabs-muredistribution-2026-05-21",
        "outcome_sink": sink,
        "graph_scope": "bounded evidence graph from canonical boundary artifact; not the complete 6,000-event trace",
        "nodes": nodes,
        "edges": edges,
        "backward_slice": sliced,
        "candidate_events": candidates,
        "candidate_count": len(candidates),
        "counterfactual_evidence": {
            "tested_candidate": "erc1271_magic_return",
            "outcome": "VIOLATION_REMOVED_BLOCKING",
            "artifact": "eval/results/e5_rcfh/mure_erc1271_final_verdict.json",
            "minimality": "bounded singleton evidence only; no exhaustive combination search",
        },
        "interpretation": "The slicer independently retains caller-controlled signer/source, ERC1271 result, authorization branch, and transfer sink on the dependency path. The ERC1271 candidate has scoped counterfactual evidence; remaining candidates are not causal verdicts.",
        "not_claimed": [
            "complete dynamic taint over the full trace",
            "global actual cause",
            "exhaustive minimal causal set",
        ],
    }
    OUT.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"candidate_count": len(candidates), "slice": sliced}, indent=2))


if __name__ == "__main__":
    main()

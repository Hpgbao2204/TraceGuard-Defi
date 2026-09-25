"""Validate packed reserve predicates against the proof-bound VETH state."""
from __future__ import annotations

import json
from pathlib import Path

from eval.e5.state_coupling import ConsistencyPredicate, StateNode, state_consistency_gate

ROOT = Path(__file__).resolve().parents[2]
CASE = "defihacklabs-veth-2024-11-14"
POOL = "0x582d17d24127cfdcbc8c4e0a40c12d77b2e7a48d"
SLOT = "0x" + "00" * 31 + "08"
MASK112 = (1 << 112) - 1


def main() -> None:
    context = ROOT / "eval/results/m4/b2-contexts-fresh" / CASE
    row = json.loads((context / "prestates.json").read_text())[57]
    state = row["trace"][POOL]
    word = int(state["storage"][SLOT], 16)
    values = {
        "reserve_word": word,
        "reserve0": word & MASK112,
        "reserve1": (word >> 112) & MASK112,
        "timestamp": word >> 224,
    }
    nodes = (
        StateNode("reserve_word", "storage", POOL, SLOT, "b2:prestate-proof:index=57"),
        StateNode("reserve0", "derived_accounting", provenance="uniswapv2:packed-slot8"),
        StateNode("reserve1", "derived_accounting", provenance="uniswapv2:packed-slot8"),
        StateNode("timestamp", "derived_accounting", provenance="uniswapv2:packed-slot8"),
    )
    predicates = (
        ConsistencyPredicate("reserve0-packed", "PACKED_FIELD", ("reserve_word",), "reserve0", (0, 112), "uniswapv2:slot8", "HIGH", "v1"),
        ConsistencyPredicate("reserve1-packed", "PACKED_FIELD", ("reserve_word",), "reserve1", (112, 112), "uniswapv2:slot8", "HIGH", "v1"),
        ConsistencyPredicate("timestamp-packed", "PACKED_FIELD", ("reserve_word",), "timestamp", (224, 32), "uniswapv2:slot8", "HIGH", "v1"),
    )
    result = state_consistency_gate(values, nodes, (), predicates, seeds=("reserve_word",))
    artifact = {
        "schema_version": 1,
        "artifact": "e5-veth-packed-predicate-validation",
        "corpus_id": "m4-frozen-20",
        "case_id": CASE,
        "state_index": 57,
        "result": result,
        "mutation_authorized": False,
        "scope": "packed-field validation only; no token-balance coupling and no replay",
    }
    out = ROOT / "eval/results/e5_rcfh/state_coupling/veth_packed_predicates.json"
    out.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": result["status"], "predicate_status": result["predicate_result"]["status"], "out": str(out)}, indent=2))


if __name__ == "__main__":
    main()

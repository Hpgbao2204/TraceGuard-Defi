"""Extract a fail-closed coupling candidate from the VETH B2 evidence.

This does not authorize a coupled mutation. It records the packed reserve
layout and token-flow participants that must be reviewed/validated before an
ERC-20 balance coupling can be promoted to a consistency edge.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASE = "defihacklabs-veth-2024-11-14"
POOL = "0x582d17d24127cfdcbc8c4e0a40c12d77b2e7a48d"
SLOT = "0x" + "00" * 31 + "08"
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


def main() -> None:
    context = ROOT / "eval/results/m4/b2-contexts-fresh" / CASE
    pre_rows = json.loads((context / "prestates.json").read_text())
    post_rows = json.loads((context / "poststates.json").read_text())
    state_index = next(i for i, row in enumerate(pre_rows)
                       if POOL in {str(a).lower() for a in row.get("trace", {})})
    pre = pre_rows[state_index]["trace"][POOL]
    post = post_rows[state_index]["poststate"].get(POOL, {})
    pre_word = int(pre["storage"][SLOT], 16)
    post_word = int(post.get("storage", {}).get(SLOT, pre["storage"][SLOT]), 16)

    receipt = json.loads((context / "receipts.json").read_text())[state_index]["receipt"]
    token_addresses = set()
    transfer_logs = []
    for log in receipt.get("logs", []):
        topics = log.get("topics", [])
        if not topics or topics[0].lower() != TRANSFER_TOPIC:
            continue
        frm = "0x" + topics[1][-40:] if len(topics) > 1 else None
        to = "0x" + topics[2][-40:] if len(topics) > 2 else None
        if POOL in {str(frm).lower(), str(to).lower()}:
            token = log["address"].lower()
            token_addresses.add(token)
            transfer_logs.append({"token": token, "from": frm, "to": to,
                                  "data": log.get("data"),
                                  "log_index": log.get("logIndex")})

    artifact = {
        "schema_version": 1,
        "artifact": "e5-state-coupling-candidate",
        "corpus_id": "m4-frozen-20",
        "case_id": CASE,
        "status": "CANDIDATE_NOT_AUTHORIZED",
        "reason": "token-flow evidence identifies possible pool-balance coupling, but does not prove a mutation predicate",
        "mutation_authorized": False,
        "state_index": state_index,
        "nodes": [
            {"node_id": "pool.reserve_word", "kind": "storage", "address": POOL,
             "key": SLOT, "provenance": f"b2:prestates/poststates:index={state_index}"},
            *[{"node_id": f"pool.erc20_balance:{token}", "kind": "erc20_balance",
               "address": POOL, "key": token,
               "provenance": f"b2:receipt:Transfer:index={state_index}"}
              for token in sorted(token_addresses)],
        ],
        "candidate_edges": [
            {"source": "pool.reserve_word", "target": f"pool.erc20_balance:{token}",
             "relation": "READ_DEPENDENCY",
             "provenance": "UniswapV2 reserve/balance relationship requires semantic validation"}
            for token in sorted(token_addresses)
        ],
        "packed_field": {
            "node_id": "pool.reserve_word", "offset": 0, "width": 224,
            "fields": ["reserve0:uint112", "reserve1:uint112"],
            "timestamp": {"offset": 224, "width": 32},
            "pre_word": str(pre_word), "post_word": str(post_word),
        },
        "transfer_log_count_involving_pool": len(transfer_logs),
        "token_addresses": sorted(token_addresses),
        "transfer_logs": transfer_logs,
    }
    out = ROOT / "eval/results/e5_rcfh/state_coupling/veth_candidate.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"out": str(out), "tokens": len(token_addresses),
                      "transfer_logs": len(transfer_logs),
                      "mutation_authorized": False}, indent=2))


if __name__ == "__main__":
    main()

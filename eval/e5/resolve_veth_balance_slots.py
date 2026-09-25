"""Fail-closed balanceOf(pool) slot scan for the VETH B2 prestate."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASE = "defihacklabs-veth-2024-11-14"
POOL = "0x582d17d24127cfdcbc8c4e0a40c12d77b2e7a48d"
TOKENS = [
    "0x280a8955a11fcd81d72ba1f99d265a48ce39ac2e",
    "0xab181941a6096296ecf1b0859ea65c797676d428",
]


def mapping_slot(slot: int) -> str:
    return subprocess.check_output(
        ["cast", "index", "address", POOL, str(slot)],
        text=True,
    ).strip().lower()


def main() -> None:
    context = ROOT / "eval/results/m4/b2-contexts-fresh" / CASE
    row = json.loads((context / "prestates.json").read_text())[57]
    trace = row["trace"]
    results = []
    for token in TOKENS:
        account = trace.get(token, {})
        storage = {str(k).lower(): v for k, v in account.get("storage", {}).items()}
        hits = []
        for slot in range(33):
            key = mapping_slot(slot)
            if key in storage:
                hits.append({"slot": slot, "key": key, "value": storage[key]})
        # A single hit is not enough for this resolver's proof/layout rule.
        # Keep it distinct from a uniquely proof-bound resolution.
        status = "SLOT_SINGLE_HIT_UNVERIFIED" if len(hits) == 1 else "SLOT_AMBIGUOUS" if hits else "SLOT_UNRESOLVED"
        results.append({"token": token, "status": status, "hits": hits,
                        "resolver_version": "veth-balance-slot-scan-v1"})
    artifact = {
        "schema_version": 1,
        "artifact": "e5-veth-balance-slot-resolution",
        "corpus_id": "m4-frozen-20",
        "case_id": CASE,
        "state_index": 57,
        "pool": POOL,
        "rule": "scan mapping slot indices 0..32; do not select ambiguous or single-hit slots without proof-bound layout evidence",
        "mutation_authorized": False,
        "results": results,
    }
    out = ROOT / "eval/results/e5_rcfh/state_coupling/veth_balance_slot_resolution.json"
    out.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"out": str(out), "results": results}, indent=2))


if __name__ == "__main__":
    main()

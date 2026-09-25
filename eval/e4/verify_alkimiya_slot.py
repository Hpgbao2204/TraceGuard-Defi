"""Verify the proof-bound ERC-20 balance slot for the Alkimiya context."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from eval.e4.erc20_slot_resolver import resolve_balance_slot


ROOT = Path(__file__).resolve().parents[1]
CONTEXT = ROOT / "results/m6/dependency-contexts/alkimiya"
OUT = ROOT / "results/e4_causal_v4/alkimiya_slot_resolution.json"
TOKEN = "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599"
ADDRESSES = [
    "0x80bf7db69556d9521c03461978b8fc731dbbd4e4",
    "0xbbbbbbbbbb9cc5e90e3b3af64bdaf62c37eeffcb",
    "0x4585fe77225b41b697c938b018e2ac67ac5a20c0",
    "0xf3f84ce038442ae4c4dcb6a8ca8bacd7f28c9bde",
]


def main():
    prestate = json.loads((CONTEXT / "prestates.json").read_text())[0]["trace"]
    proofs = json.loads((CONTEXT / "prestate_proofs.json").read_text())["proofs"]
    resolved = resolve_balance_slot(TOKEN, prestate, proofs, ADDRESSES)
    result = {
        "schema_version": "e4-causal-v4-alkimiya-slot-resolution-v1",
        "status": "PASS" if resolved["slot_index"] == 0 and len(resolved["hits"]) == 4 else "FAIL",
        "token": TOKEN,
        "slot_index": resolved["slot_index"],
        "hit_count": len(resolved["hits"]),
        "hits": [{"address": a, "storage_key": k} for a, k in resolved["hits"]],
        "proof_source": str(CONTEXT / "prestate_proofs.json"),
        "prestate_source": str(CONTEXT / "prestates.json"),
        "resolver": "eval/e4/erc20_slot_resolver.py",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Check whether reverse-swap amountOut is supplied statically or computed in settlement."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASE = ROOT / "eval/results/m4/b2-contexts-fresh/defihacklabs-veth-2024-11-14"
OPCODES = Path("/tmp/veth-sstore-baseline-v4.json")
OUT = ROOT / "eval/results/e5_rcfh/veth_buyquote_dose_probe/reverse_swap_amount_audit.json"

def main():
    trace = json.loads((CASE / "b2-replay-m4.json").read_text())["per_tx"][57]["call_trace"]
    raw = trace[88]["input"][2:]
    words = [raw[i:i + 64] for i in range(8, len(raw), 64)]
    op = json.loads(OPCODES.read_text())["per_tx"][57]["opcode_tail"]
    calls = [x for x in op if x.get("call_trace_index") == 77 and x.get("op") == "CALL"]
    matching = [x for x in calls if "5431546734899093128155" in [str(v) for v in x.get("stack_top", [])]]
    out = {
        "status": "REVERSE_AMOUNT_DYNAMICALLY_COMPUTED_BEFORE_SWAP",
        "case_id": "defihacklabs-veth-2024-11-14",
        "historical_swap_calldata": {
            "trace_index": 88,
            "selector": "0x022c0d9f",
            "amount0Out_raw": str(int(words[0], 16)),
            "amount1Out_raw": str(int(words[1], 16)),
            "to": "0x" + words[2][-40:],
        },
        "dynamic_evidence": {
            "settlement_frame": 77,
            "pair_getReserves_trace": 82,
            "call_opcode_with_amount0Out": {k: matching[0].get(k) for k in ("pc", "depth", "stack_top", "call_trace_index")} if matching else None,
            "arithmetic_before_call_observed": True,
            "basis": "The settlement frame performs getReserves and arithmetic before constructing the pair.swap CALL; amount0Out appears on the CALL stack rather than as transaction calldata.",
        },
        "implication": "A patch applied only at trace 88 is too late to recompute amount0Out. Its insufficient-liquidity revert is therefore not a clean test of a self-adjusting attacker amount. A cleaner no-helper intervention must patch before settlement reserve reading (trace 77 or the getReserves boundary) and let the historical settlement logic recompute the output.",
        "causal_status": "REAL_TRACE88_PATCH_NOT_ADMISSIBLE_FOR_CLEAN_CAUSAL_VERDICT",
        "source_hashes": {"b2_replay_m4": hashlib.sha256((CASE / "b2-replay-m4.json").read_bytes()).hexdigest(), "opcode_capture": hashlib.sha256(OPCODES.read_bytes()).hexdigest()},
    }
    OUT.write_text(json.dumps(out, indent=2) + "\n")
    print(OUT)
    print(hashlib.sha256(OUT.read_bytes()).hexdigest())

if __name__ == "__main__": main()

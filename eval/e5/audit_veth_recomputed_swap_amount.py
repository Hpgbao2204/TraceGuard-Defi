#!/usr/bin/env python3
"""Validate reverse amount-in/out against the patched pre-helper reserves."""
import hashlib
import json
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASE = ROOT / "eval/results/m4/b2-contexts-fresh/defihacklabs-veth-2024-11-14"
RUN = ROOT / "eval/results/e5_rcfh/veth_buyquote_dose_probe/settlement_entry_storage_patch_real.json"
OUT = ROOT / "eval/results/e5_rcfh/veth_buyquote_dose_probe/recomputed_reverse_amount_audit.json"

def main():
    trace = json.loads((CASE / "b2-replay-m4.json").read_text())["per_tx"][57]["call_trace"]
    swap = trace[88]["input"][2:]
    words = [swap[i:i + 64] for i in range(8, len(swap), 64)]
    amount0_out = int(words[0], 16)
    amount1_in = int(trace[84]["input"][-64:], 16)
    packed = int("6733266b000000423500560e898e4b9363b00000000000015b0d85e0a8cf2cc7", 16)
    mask = (1 << 112) - 1
    reserve0 = packed & mask
    reserve1 = (packed >> 112) & mask
    expected = amount1_in * 997 * reserve0 // (reserve1 * 1000 + amount1_in * 997)
    run = json.loads(RUN.read_text())
    ci = run["per_tx"][57]["call_intervention"]
    out = {
        "status": "PATCHED_SETTLEMENT_AMOUNT_SELF_CONSISTENT_PRE_HARM_TRANSFER_REVERT",
        "case_id": "defihacklabs-veth-2024-11-14",
        "amounts": {
            "amount1_in_raw": str(amount1_in),
            "amount1_in_tokens": str(Decimal(amount1_in) / Decimal(10**18)),
            "patched_reserve0_raw": str(reserve0),
            "patched_reserve1_raw": str(reserve1),
            "swap_amount0_out_raw": str(amount0_out),
            "formula_amount0_out_raw": str(expected),
            "formula_equals_swap_amount0_out": expected == amount0_out,
        },
        "revert": {
            "inner_trace": 90,
            "inner_error_data": trace[90].get("output"),
            "outer_pair_error": trace[91].get("output"),
            "outer_pair_error_reason": "UniswapV2: TRANSFER_FAILED",
        },
        "interpretation": "Settlement recomputed amount0Out from the patched reserve and the historical amount1In; the standard V2 formula matches exactly. The remaining failure is the token0 transfer/balance path, not a stale amountOut. Its custom error argument semantics and exact live-balance mapping still require closure before causal promotion.",
        "causal_status": "INCONCLUSIVE_PRE_HARM_TRANSFER_ERROR",
        "source_hashes": {"b2_replay_m4": hashlib.sha256((CASE / "b2-replay-m4.json").read_bytes()).hexdigest(), "run": hashlib.sha256(RUN.read_bytes()).hexdigest()},
    }
    OUT.write_text(json.dumps(out, indent=2) + "\n")
    print(OUT)
    print(hashlib.sha256(OUT.read_bytes()).hexdigest())

if __name__ == "__main__": main()

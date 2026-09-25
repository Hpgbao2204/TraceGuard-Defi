"""Audit VETH pair swap amounts against post-transfer balance observations.

This is diagnostic only.  It checks whether the amount requested in the pair
swap is compatible with the token balances returned by the pair's balanceOf
calls in the canonical dose runs.  It does not assign a harm or causal verdict.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "eval/results/e5_rcfh/veth_buyquote_dose_probe"
OUT = BASE / "pair_balance_semantics_audit.json"


def word(output: str) -> int:
    return int(output.removeprefix("0x"), 16)


def main() -> None:
    rows = []
    for pct in (90, 95, 100):
        tx = json.loads((BASE / f"dose_{pct:03d}.json").read_text())["per_tx"][57]
        trace = tx["call_trace"]
        swap_input = trace[24]["input"].removeprefix("0x")
        calldata_amount1_out = int(swap_input[72:136], 16)
        logs = tx["logs"]
        event_amount1_out = int(logs[7]["data"].removeprefix("0x")[192:256], 16)
        transfer_amount = int(logs[5]["data"].removeprefix("0x"), 16)
        pair_balance_token0 = word(trace[30]["output"])
        pair_balance_token1 = word(trace[33]["output"])
        rows.append({
            "dose_percent": pct,
            "swap_calldata_amount1_out_raw": str(calldata_amount1_out),
            "swap_event_amount1_out_raw": str(event_amount1_out),
            "token1_transfer_amount_raw": str(transfer_amount),
            "pair_balance_token0_after_funding_raw": str(pair_balance_token0),
            "pair_balance_token1_after_funding_raw": str(pair_balance_token1),
            "calldata_amount1_out_gt_pair_token1_balance": calldata_amount1_out > pair_balance_token1,
            "event_amount1_out_gt_pair_token1_balance": event_amount1_out > pair_balance_token1,
            "event_transfer_match": event_amount1_out == transfer_amount,
            "event_amount1_out_to_pair_token1_balance_ratio": event_amount1_out / pair_balance_token1,
            "post_balance_plus_output_reconstructs_reserve1": (
                pair_balance_token1 + event_amount1_out
                == int("423500560e898e4b9363b0", 16)
            ),
            "trace_indices": {
                "swap": 24,
                "pair_token0_balanceOf": 29,
                "pair_token0_return": 30,
                "pair_token1_balanceOf": 31,
                "pair_token1_return": 33,
            },
        })

    OUT.write_text(json.dumps({
        "schema_version": 1,
        "artifact": "e5-veth-pair-balance-semantics-audit",
        "case_id": "defihacklabs-veth-2024-11-14",
        "scope": "diagnostic trace audit; no causal or harm verdict",
        "interpretation": (
            "The swap calldata argument is larger than the post-transfer balance "
            "because it is the amount sent out. The committed Swap event amount "
            "matches the token1 Transfer amount, and output plus post-transfer "
            "balance reconstructs reserve1 at every tested dose. The apparent "
            "anomaly came from decoding reserve1 with a missing trailing zero."
        ),
        "rows": rows,
        "required_follow_up": [
            "identify token0/token1 addresses and decimals at the historical state",
            "decode the pair implementation and transfer/balanceOf semantics",
            "compare balanceOf deltas with Transfer event amounts",
            "recompute the invariant using observed balances, not only getReserves",
        ],
    }, indent=2) + "\n")
    print(OUT)


if __name__ == "__main__":
    main()

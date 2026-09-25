"""Materialize the VETH dose value-flow chain with trace provenance."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "eval/results/e5_rcfh/veth_buyquote_dose_probe"
OUT = BASE / "domino_value_flow.json"
R0 = int("15b0d85e0a8cf2cc7", 16)
R1 = int("423500560e898e4b9363b0", 16)


def word(data: str, index: int) -> int:
    body = data.removeprefix("0x")
    return int(body[index * 64:(index + 1) * 64], 16)


def calldata_word(data: str, index: int) -> int:
    body = data.removeprefix("0x")[8:]
    return int(body[index * 64:(index + 1) * 64], 16)


def main() -> None:
    rows = []
    for pct in (90, 95, 100):
        tx = json.loads((BASE / f"dose_{pct:03d}.json").read_text())["per_tx"][57]
        trace = tx["call_trace"]
        logs = tx["logs"]
        buy = trace[17]
        amount = calldata_word(buy["input"], 1)
        primary_swap = trace[24]
        swap_amount1_out = calldata_word(primary_swap["input"], 1)
        swap_event = logs[7]
        event_amount1_out = word(swap_event["data"], 3)
        token1_transfer = int(logs[5]["data"].removeprefix("0x"), 16)
        pair_token1_after = word(trace[33]["output"], 0)
        later_settlement = calldata_word(trace[77]["input"], 1)
        expected = amount * 997 * R1 // (R0 * 1000 + amount * 997)
        rows.append({
            "dose_percent": pct,
            "values_raw": {
                "buyQuote_msg_value": str(buy["value"]),
                "buyQuote_amount_argument": str(amount),
                "cashIn_msg_value_trace20": str(trace[20]["value"]),
                "factory_to_pair_token0_transfer_log10": str(int(logs[10]["data"], 16)),
                "primary_swap_calldata_amount1_out_trace24": str(swap_amount1_out),
                "primary_swap_event_amount1_out_log7": str(event_amount1_out),
                "token1_pair_to_attacker_transfer_log5": str(token1_transfer),
                "pair_token1_balance_after_primary_swap_trace33": str(pair_token1_after),
                "settlement_amount_trace77": str(later_settlement),
            },
            "checks": {
                "input_equals_msg_value": amount == int(buy["value"]),
                "msg_value_equals_cashIn_value": buy["value"] == trace[20]["value"],
                "primary_swap_event_equals_calldata": event_amount1_out == swap_amount1_out,
                "primary_swap_event_equals_token1_transfer": event_amount1_out == token1_transfer,
                "standard_v2_formula_output": str(expected),
                "formula_equals_primary_swap_event": expected == event_amount1_out,
                "output_plus_pair_balance_equals_reserve1": event_amount1_out + pair_token1_after == R1,
            },
            "provenance": {
                "buyQuote": "call_trace[17]",
                "cashIn": "call_trace[20]",
                "primary_swap": "call_trace[24]",
                "primary_swap_event": "logs[7]",
                "token1_transfer": "logs[5]",
                "pair_token1_balance": "call_trace[33]",
                "settlement": "call_trace[77]",
            },
        })

    OUT.write_text(json.dumps({
        "schema_version": 1,
        "artifact": "e5-veth-domino-value-flow",
        "case_id": "defihacklabs-veth-2024-11-14",
        "reserve_source": "primary getReserves return at call_trace[19]",
        "reserve0_raw": str(R0),
        "reserve1_raw": str(R1),
        "interpretation": (
            "The domino is a deterministic value-propagation chain: changing "
            "the coupled buyQuote amount/msg.value changes the token0 input to "
            "the primary pair swap; the standard V2 formula changes amount1Out; "
            "the committed token1 transfer and pair post-swap balance change; "
            "the later settlement amount changes accordingly. All checked links "
            "match the same execution topology. This establishes the mechanism "
            "of the dose effect, not root-cause necessity or economic harm by "
            "itself."
        ),
        "rows": rows,
        "status": "DOMINO_VALUE_PROPAGATION_EXPLAINED_DIAGNOSTIC_ONLY",
    }, indent=2) + "\n")
    print(OUT)


if __name__ == "__main__":
    main()

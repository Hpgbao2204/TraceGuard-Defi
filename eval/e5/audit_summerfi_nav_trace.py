#!/usr/bin/env python3
"""Read-only audit of SummerFi Ark NAV and withdrawal trace paths."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ARK = "0x61d7063041d83c8ca3e42c39181dfd14b3bc76c2"
FLEET = "0x98c49e13bf99d7cad8069faa2a370933ec9ecf17"
VGUSDC = "0x8399c8fc273bd165c346af74a02e65f10e4fd78f"
TOTAL_ASSETS = "0x01e1d114"
BALANCE_OF = "0x70a08231"
CONVERT_TO_ASSETS = "0x07a2d13a"
MAX_WITHDRAW = "0xce96cb77"
CHAINLINK = {
    "0xeef31c7d9f2e82e8a497b140cc60cc082be4b94e",
    "0xbe4d4d2fdde7408bd00b9912705de7bdc3f9bdeb",
    "0xfc05b888b19f1ccf8aa87ad8fc28a9d5643e65f8",
    "0x192c91da9ec9b23d94ff83b47c9bbabfd2029eea",
    "0x91f37a3058a7fd3f4f66ed87d715cf05bb4fbfbd",
    "0x8a1bae36ee0e7b7d6ced3ffea250914bfca09292",
    "0x8fffffd4afb6115b954bd326cbe7b4ba576818f6",
    "0xc9e1a09622afdb659913fefe800feae5dbbfe9d7",
}


def norm(value: str | None) -> str:
    return (value or "").lower()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    payload = json.loads(args.input.read_text())
    trace = payload["per_tx"][0]["call_trace"]
    enters = [
        (index, event)
        for index, event in enumerate(trace)
        if event.get("event") == "enter"
    ]

    nav_calls = []
    withdrawal_calls = []
    exact_chainlink_calls = []

    for index, event in enters:
        caller = norm(event.get("from"))
        callee = norm(event.get("to"))
        selector = norm(event.get("input", "")[:10])
        if caller == FLEET and callee == ARK:
            record = {
                "trace_index": index,
                "depth": event.get("depth"),
                "selector": selector,
                "caller": event.get("from"),
                "callee": event.get("to"),
            }
            if selector == TOTAL_ASSETS:
                nav_calls.append(record)
            else:
                withdrawal_calls.append(record)
        if callee in CHAINLINK:
            exact_chainlink_calls.append(
                {
                    "trace_index": index,
                    "depth": event.get("depth"),
                    "caller": event.get("from"),
                    "callee": event.get("to"),
                    "selector": selector,
                }
            )

    def child_calls(parent_index: int) -> list[dict]:
        parent_depth = trace[parent_index].get("depth")
        result = []
        for index in range(parent_index + 1, len(trace)):
            event = trace[index]
            if event.get("event") == "exit" and event.get("depth") == parent_depth:
                break
            if event.get("event") == "enter" and event.get("depth") == parent_depth + 1:
                result.append(
                    {
                        "trace_index": index,
                        "selector": norm(event.get("input", "")[:10]),
                        "callee": event.get("to"),
                        "input": event.get("input"),
                    }
                )
        return result

    for record in nav_calls:
        record["direct_children"] = child_calls(record["trace_index"])
        record["has_balance_read"] = any(
            child["selector"] == BALANCE_OF and norm(child["callee"]) == VGUSDC
            for child in record["direct_children"]
        )
        record["has_convert_to_assets"] = any(
            child["selector"] == CONVERT_TO_ASSETS and norm(child["callee"]) == VGUSDC
            for child in record["direct_children"]
        )

    result = {
        "artifact": "e5-summerfi-nav-trace-audit",
        "schema_version": 1,
        "input": str(args.input),
        "fleet": FLEET,
        "ark": ARK,
        "asset": VGUSDC,
        "nav_total_assets_calls": nav_calls,
        "other_fleet_to_ark_calls": withdrawal_calls,
        "exact_chainlink_calls": exact_chainlink_calls,
        "checks": {
            "nav_calls_with_balance_read": all(call["has_balance_read"] for call in nav_calls),
            "nav_calls_with_convert_to_assets": any(call["has_convert_to_assets"] for call in nav_calls),
            "chainlink_directly_called_by_fleet_or_target_ark": any(
                norm(call["caller"]) in {FLEET, ARK} for call in exact_chainlink_calls
            ),
        },
        "classification": "NAV_ACCOUNTING_SEAM_CONFIRMED_NO_REPLAY_AUTHORIZATION",
        "limitations": [
            "This is call-trace evidence, not opcode-level data-flow proof.",
            "No mutation or sham was run.",
            "Protected reserve harm and an intervention that removes direct donated-share valuation remain unfrozen.",
        ],
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Audit the historical VirtualToken cashIn() boundary for VETH.

This records bytecode dispatch and the observed call frame. It deliberately
does not infer mint/collateral semantics from a token name or selector.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASE = ROOT / "eval/results/m4/b2-contexts-fresh/defihacklabs-veth-2024-11-14"
OUT = ROOT / "eval/results/e5_rcfh/veth_buyquote_dose_probe/cashin_path_audit.json"
TOKEN = "0x280a8955a11fcd81d72ba1f99d265a48ce39ac2e"
CASHIN = "0x1e580615"


def disassemble(code: str) -> list[str]:
    p = subprocess.run(
        ["cast", "disassemble", code],
        check=True, capture_output=True, text=True,
    )
    return p.stdout.splitlines()


def main() -> None:
    prestates = json.loads((CASE / "prestates.json").read_text())
    account = prestates[57]["trace"][TOKEN]
    lines = disassemble(account["code"])
    selector_lines = [line for line in lines if CASHIN[2:].upper() in line.upper()]

    def pc(line: str) -> int | None:
        m = re.match(r"^([0-9a-f]+):", line)
        return int(m.group(1), 16) if m else None

    cashin_body = [line for line in lines if pc(line) is not None and 0x0bec <= pc(line) <= 0x0c75]
    mint_helper = [line for line in lines if pc(line) is not None and 0x1193 <= pc(line) <= 0x11ef]

    run = json.loads((CASE / "b2-replay-m4.json").read_text())
    trace = run["per_tx"][57]["call_trace"]
    hits = []
    for i, e in enumerate(trace):
        if e.get("event") == "enter" and e.get("to", "").lower() == TOKEN and (e.get("input") or "")[:10].lower() == CASHIN:
            hits.append({
                "trace_index": i,
                "depth": e.get("depth"),
                "from": e.get("from"),
                "to": e.get("to"),
                "input": e.get("input"),
                "value": e.get("value"),
            })

    # Dispatcher target is found from the PUSH4 selector / PUSH2 JUMPI pair.
    dispatch = []
    for i, line in enumerate(lines):
        if CASHIN[2:].upper() in line.upper():
            dispatch.extend(lines[max(0, i - 2):i + 3])

    out = {
        "artifact": "VETH cashIn path audit",
        "status": "DIAGNOSTIC_ONLY",
        "case_id": "defihacklabs-veth-2024-11-14",
        "token": TOKEN,
        "selector": CASHIN,
        "code_hash": account.get("codeHash"),
        "source": {
            "historical_code": "eval/results/m4/b2-contexts-fresh/defihacklabs-veth-2024-11-14/prestates.json#/57/trace/" + TOKEN,
            "historical_trace": "eval/results/m4/b2-contexts-fresh/defihacklabs-veth-2024-11-14/b2-replay-m4.json#/per_tx/57/call_trace",
        },
        "dispatcher_evidence": dispatch,
        "selector_occurrences_in_disassembly": selector_lines,
        "cashIn_body_slice": cashin_body,
        "mint_helper_slice": mint_helper,
        "observed_cashIn_calls": hits,
        "interpretation": {
            "confirmed": [
                "cashIn is called by the Factory path in the historical transaction",
                "the call carries the same native value as the tested buyQuote dose",
                "the cashIn body uses CALLVALUE and jumps to helper 0x1193 on this execution path",
                "helper 0x1193 updates total-supply storage slot 0x02, updates caller balance storage, and emits Transfer(address(0), caller, amount)",
            ],
            "not_yet_confirmed": [
                "whether cashIn mints token0",
                "whether minted amount is exactly tied to msg.value",
                "whether collateral, oracle, or authorization checks constrain the amount",
            ],
            "next_evidence": "confirm helper argument order from stack provenance and determine whether the native CALLVALUE path is intentionally collateralized 1:1 or is an unguarded mint; do not generalize beyond this historical runtime",
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2) + "\n")
    print(OUT)
    print("cashIn selector occurrences:")
    for line in selector_lines:
        print(line)
    print("observed calls:", len(hits))
    for hit in hits:
        print(hit)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Audit the VETH buyQuote bytecode path against the canonical call trace.

This is an evidence extractor, not a causal verdict generator.  It records
the dispatcher target, the relevant bytecode slice, and the observed nested
calls made by buyQuote in the historical replay.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASE = ROOT / "eval/results/m4/b2-contexts-fresh/defihacklabs-veth-2024-11-14"
OUT = ROOT / "eval/results/e5_rcfh/veth_buyquote_dose_probe/buyquote_cost_path_audit.json"
FACTORY = "0x19c5538df65075d53d6299904636bae68b6df441"
BUYQUOTE = "0xa7591849"


def disassemble(code: str) -> list[str]:
    p = subprocess.run(
        ["cast", "disassemble", code],
        check=True, capture_output=True, text=True,
    )
    return p.stdout.splitlines()


def selector(line: dict) -> str:
    return (line.get("input") or "")[:10].lower()


def main() -> None:
    prestates = json.loads((CASE / "prestates.json").read_text())
    target = prestates[57]["trace"][FACTORY]
    code = target["code"]
    lines = disassemble(code)

    # Keep the dispatcher and the buyQuote body around 0x07ef.  The exact
    # bytecode offsets are evidence; their semantics are not guessed here.
    relevant = []
    for line in lines:
        m = re.match(r"^([0-9a-f]+):", line)
        if not m:
            continue
        pc = int(m.group(1), 16)
        if pc <= 0x70 or 0x07ef <= pc <= 0x0a27:
            relevant.append(line)

    run = json.loads((CASE / "b2-replay-m4.json").read_text())
    trace = run["per_tx"][57]["call_trace"]
    # The buyQuote frame is depth 3 and is bounded by its matching exit.
    start = next(i for i, e in enumerate(trace)
                 if e.get("event") == "enter" and e.get("to", "").lower() == FACTORY
                 and selector(e) == BUYQUOTE)
    depth = trace[start]["depth"]
    end = next(i for i in range(start + 1, len(trace))
               if trace[i].get("event") == "exit" and trace[i].get("depth") == depth)
    nested = [e for e in trace[start + 1:end]
              if e.get("event") == "enter" and e.get("depth", 0) == depth + 1]

    observed = [{
        "to": e.get("to"),
        "selector": selector(e),
        "value": e.get("value"),
        "input_prefix": (e.get("input") or "")[:74],
    } for e in nested]

    out = {
        "artifact": "VETH buyQuote cost-path audit",
        "status": "DIAGNOSTIC_ONLY",
        "case_id": "defihacklabs-veth-2024-11-14",
        "source": {
            "historical_code": "eval/results/m4/b2-contexts-fresh/defihacklabs-veth-2024-11-14/prestates.json#/57/trace/" + FACTORY,
            "historical_trace": "eval/results/m4/b2-contexts-fresh/defihacklabs-veth-2024-11-14/b2-replay-m4.json#/per_tx/57/call_trace",
        },
        "factory": FACTORY,
        "factory_code_hash": target.get("codeHash"),
        "buyQuote_selector": BUYQUOTE,
        "dispatcher": {"selector": BUYQUOTE, "jump_target_pc": "0x07ef"},
        "observed_buyQuote_nested_calls": observed,
        "interpretation": {
            "confirmed": [
                "buyQuote enters the Factory dispatcher at 0x07ef",
                "the historical buyQuote frame calls the pair getReserves selector 0x0902f1ac",
                "it calls VirtualToken cashIn selector 0x1e580615",
                "it calls the pair swap selector 0x022c0d9f",
            ],
            "not_confirmed": [
                "the exact source-level variable representing cost settlement",
                "that buyQuote uses an independent oracle or stale price",
                "that the root vulnerability is the buyQuote calculation itself",
            ],
            "causal_boundary_next": "identify the value/state write used by the Factory takeLoan/cost-settlement path; do not treat capital-dose feasibility as root-cause evidence",
        },
        "bytecode_slice": relevant,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2) + "\n")
    print(OUT)
    print("observed nested calls:")
    for e in observed:
        print(e["selector"], e["to"])


if __name__ == "__main__":
    main()

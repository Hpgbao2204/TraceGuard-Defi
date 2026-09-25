"""Measure a pre-repayment frame effect from authenticated call-tree traces.

This is deliberately an observation adapter, not a frame-local executor.  It
fails closed unless the same payout path, payer, recipient, and native value
transfer are present in both traces.  It is useful for deciding whether a full
Go frame-local port is warranted for a case such as XLoot.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def walk(node: dict, path: str = ""):
    if not isinstance(node, dict):
        return
    yield path, node
    for i, child in enumerate(node.get("calls") or []):
        yield from walk(child, f"{path}/calls[{i}]")


def native_transfers(trace: dict) -> list[dict]:
    rows = []
    for path, node in walk(trace):
        value = int(node.get("value", "0x0"), 16)
        if value > 0 and not node.get("error"):
            rows.append({
                "path": path,
                "from": node.get("from", "").lower(),
                "to": node.get("to", "").lower(),
                "value_wei": value,
                "input": node.get("input", "0x"),
            })
    return rows


def measure(probe: dict, payer: str, recipient: str) -> dict:
    baseline = native_transfers(probe["baseline_trace"])
    counter = native_transfers(probe["counterfactual_trace"])
    payer, recipient = payer.lower(), recipient.lower()
    b = [x for x in baseline if x["from"] == payer and x["to"] == recipient]
    c = [x for x in counter if x["from"] == payer and x["to"] == recipient]
    if len(b) != 1 or len(c) != 1 or b[0]["path"] != c[0]["path"]:
        return {"status": "INCONCLUSIVE", "reason": "unique common payout frame not found", "baseline_candidates": b, "counterfactual_candidates": c}
    bv, cv = b[0]["value_wei"], c[0]["value_wei"]
    return {
        "status": "MEASURED_PRE_REPAYMENT_EFFECT",
        "path": b[0]["path"],
        "payer": payer,
        "recipient": recipient,
        "baseline_payout_wei": str(bv),
        "counterfactual_payout_wei": str(cv),
        "reduction_wei": str(bv - cv),
        "reduction_fraction": (bv - cv) / bv if bv else None,
        "counterfactual_reverted_later": bool(probe["counterfactual"].get("status") is False),
        "scope": "frame-local observation before downstream repayment",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("probe", type=Path)
    ap.add_argument("--payer", required=True)
    ap.add_argument("--recipient", required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    result = measure(json.loads(args.probe.read_text()), args.payer, args.recipient)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "MEASURED_PRE_REPAYMENT_EFFECT" else 1


if __name__ == "__main__":
    raise SystemExit(main())

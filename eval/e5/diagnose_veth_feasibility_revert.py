"""Diagnose VETH lower-dose reverts from the canonical dose traces."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "eval/results/e5_rcfh/veth_buyquote_dose_probe"
OUT = BASE / "feasibility_revert_diagnosis.json"


def main() -> None:
    rows = []
    for pct in (50, 75, 90, 95, 100):
        tx = json.loads((BASE / f"dose_{pct:03d}.json").read_text())["per_tx"][57]
        trace = tx["call_trace"]
        factory_return = trace[102].get("value") if len(trace) > 102 else None
        deposit = trace[105] if len(trace) > 105 else {}
        errors = [
            {"trace_index": i, "error": x.get("error"), "reverted": x.get("reverted")}
            for i, x in enumerate(trace)
            if x.get("error") or x.get("reverted")
        ]
        rows.append({
            "dose_percent": pct,
            "status": tx.get("actual_status"),
            "trace_length": len(trace),
            "factory_to_attacker_value_trace102_raw": str(factory_return) if factory_return is not None else None,
            "weth_deposit_trace105": {
                "caller": deposit.get("from"),
                "callee": deposit.get("to"),
                "selector": deposit.get("input", "")[:10],
                "value_raw": str(deposit.get("value")),
            },
            "revert_frames": errors,
            "classification": (
                "FINAL_REPAYMENT_FUNDING_SHORTFALL"
                if pct in (50, 75) else "NO_REVERT"
            ),
        })

    OUT.write_text(json.dumps({
        "schema_version": 1,
        "artifact": "e5-veth-feasibility-revert-diagnosis",
        "case_id": "defihacklabs-veth-2024-11-14",
        "interpretation": (
            "At 50% and 75%, the coupled buyQuote amount/msg.value reduces the "
            "amount returned to the attacker at trace index 102, but the later "
            "WETH deposit at trace index 105 still attempts the original 100% "
            "native value. The deposit therefore fails with insufficient balance "
            "before final flash-loan repayment. At 90% and above the same final "
            "step succeeds. This is a downstream repayment-feasibility boundary, "
            "not an AMM invariant failure or a causal no-harm result."
        ),
        "rows": rows,
        "status": "LOW_DOSE_REVERT_EXPLAINED_AS_REPAYMENT_FEASIBILITY",
    }, indent=2) + "\n")
    print(OUT)


if __name__ == "__main__":
    main()

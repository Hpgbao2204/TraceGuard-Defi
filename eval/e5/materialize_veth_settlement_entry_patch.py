#!/usr/bin/env python3
"""Classify the pre-settlement storage patch after amount recomputation."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "eval/results/e5_rcfh/veth_buyquote_dose_probe/settlement_entry_storage_patch_real.json"
OUT = ROOT / "eval/results/e5_rcfh/veth_buyquote_dose_probe/settlement_entry_storage_patch_audit.json"

def main():
    data = json.loads(RAW.read_text())
    target = data["per_tx"][57]
    ci = target.get("call_intervention") or {}
    out = {
        "status": "INCONCLUSIVE_PRE_SETTLEMENT_PATCH_REVERT",
        "case_id": "defihacklabs-veth-2024-11-14",
        "trigger": {"selector": "0xe784a059", "depth": 3, "occurrence": 1, "trace_index": 77},
        "execution": {k: target.get(k) for k in ("actual_status", "actual_gas", "gas_match", "status_match", "logs_match", "post_state_match")},
        "revert": {"first_revert_depth": ci.get("first_revert_depth"), "first_revert_data": ci.get("first_revert_data"), "failing_child": "trace 89 token0 transfer from pair; trace 88 swap itself entered"},
        "interpretation": "Moving the patch to trace 77 lets settlement preparation read the patched reserve and recompute its swap amount, but the run reverts in the pair's token0 transfer before harm observation. This is not promoted to causal support: the no-helper live-balance materialization and transfer-side state still need closure.",
        "causal_status": "NOT_TESTABLE_PRE_HARM_REVERT_UNTIL_BALANCE_TRANSFER_STATE_CLOSED",
        "raw_sha256": hashlib.sha256(RAW.read_bytes()).hexdigest(),
    }
    OUT.write_text(json.dumps(out, indent=2) + "\n")
    print(OUT)
    print(hashlib.sha256(OUT.read_bytes()).hexdigest())

if __name__ == "__main__": main()

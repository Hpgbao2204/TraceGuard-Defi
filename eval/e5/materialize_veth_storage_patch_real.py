#!/usr/bin/env python3
"""Classify the VETH pre-helper-state storage patch without overclaiming."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "eval/results/e5_rcfh/veth_buyquote_dose_probe/reverse_storage_patch_real.json"
OUT = ROOT / "eval/results/e5_rcfh/veth_buyquote_dose_probe/reverse_storage_patch_real_audit.json"

def decode_error(data):
    if not data.startswith("0x08c379a0"):
        return None
    try:
        raw = bytes.fromhex(data[10:])
        offset = int.from_bytes(raw[:32], "big")
        length = int.from_bytes(raw[offset:offset + 32], "big")
        return raw[offset + 32:offset + 32 + length].decode()
    except Exception:
        return "MALFORMED_ERROR_STRING"

def main():
    data = json.loads(RAW.read_text())
    target = data["per_tx"][57]
    intervention = target.get("call_intervention") or {}
    revert_data = intervention.get("first_revert_data", "")
    out = {
        "status": "INCONCLUSIVE_PRE_HARM_REVERT_INSUFFICIENT_LIQUIDITY",
        "case_id": "defihacklabs-veth-2024-11-14",
        "trigger": {"selector": "0x022c0d9f", "depth": 4, "occurrence": 2, "trace_index": 88},
        "execution": {k: target.get(k) for k in ("actual_status", "actual_gas", "gas_match", "status_match", "logs_match", "post_state_match")},
        "intervention": {"application_verified": intervention.get("application_verified"), "match_count": intervention.get("match_count"), "first_revert_depth": intervention.get("first_revert_depth"), "first_revert_data": revert_data, "first_revert_reason": decode_error(revert_data), "storage_patches": intervention.get("storage_patches", [])},
        "interpretation": "The patch reaches the reverse pair.swap and reverts inside the pair with UniswapV2: INSUFFICIENT_LIQUIDITY before protected harm observation. This is consistent with the timing-subsidy hypothesis, but is not promoted to causal support because the patched live-balance state must still be checked against settlement-transfer effects and the exact no-helper counterfactual.",
        "causal_status": "NOT_TESTABLE_PRE_HARM_REVERT_UNTIL_STATE_MAPPING_CLOSED",
        "raw_sha256": hashlib.sha256(RAW.read_bytes()).hexdigest(),
    }
    OUT.write_text(json.dumps(out, indent=2) + "\n")
    print(OUT)
    print(hashlib.sha256(OUT.read_bytes()).hexdigest())

if __name__ == "__main__": main()

#!/usr/bin/env python3
"""Materialize the VETH storage-patch read-back and custom-error audit."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "eval/results/e5_rcfh/veth_buyquote_dose_probe/settlement_entry_storage_patch_real_readback.json"
OUT = ROOT / "eval/results/e5_rcfh/veth_buyquote_dose_probe/settlement_entry_storage_patch_readback_audit.json"

CUSTOM_ERROR = "0x1b113061"
CUSTOM_SIGNATURE = "DebtOverflow(address,uint256,uint256)"


def decode_debt_overflow(data: str) -> dict:
    payload = bytes.fromhex(data[10:])
    if len(payload) != 96:
        raise ValueError(f"expected 3 ABI words, got {len(payload)} bytes")
    return {
        "address": "0x" + payload[12:32].hex(),
        "arg1_raw": str(int.from_bytes(payload[32:64], "big")),
        "arg2_raw": str(int.from_bytes(payload[64:96], "big")),
        "arg1_hex": "0x" + payload[32:64].hex(),
        "arg2_hex": "0x" + payload[64:96].hex(),
    }


def main() -> None:
    data = json.loads(RAW.read_text())
    target = data["per_tx"][57]
    intervention = target["call_intervention"]
    revert_data = intervention["first_revert_data"]
    if not revert_data.startswith(CUSTOM_ERROR):
        raise ValueError(f"unexpected revert selector: {revert_data[:10]}")

    patches = intervention["storage_patches"]
    readback_pass = bool(patches) and all(p["after"] == p["read_back"] for p in patches)
    decoded = decode_debt_overflow(revert_data)
    out = {
        "status": "PATCH_READBACK_PASS_DEBT_OVERFLOW_SEMANTICS_PENDING",
        "case_id": "defihacklabs-veth-2024-11-14",
        "trigger": {
            "caller": intervention["caller"],
            "callee": intervention["callee"],
            "selector": intervention["selector"],
            "depth": intervention["depth"],
            "trace_role": "settlement_entry_before_reverse_swap",
        },
        "execution": {
            "actual_status": target["actual_status"],
            "status_match": target["status_match"],
            "gas_match": target["gas_match"],
            "logs_match": target["logs_match"],
            "post_state_match": target["post_state_match"],
            "application_verified": intervention["application_verified"],
            "match_count": intervention["match_count"],
            "first_revert_depth": intervention["first_revert_depth"],
        },
        "custom_error": {
            "selector": CUSTOM_ERROR,
            "signature": CUSTOM_SIGNATURE,
            "raw": revert_data,
            "decoded": decoded,
            "argument_semantics": "UNRESOLVED; arg1/arg2 are recorded as raw ABI words and are not labeled available/required.",
        },
        "storage_patch_readback": {
            "all_after_equals_read_back": readback_pass,
            "patches": patches,
            "scope": "pair reserve packed slot plus token0/token1 balanceOf(pair) mapping cells",
        },
        "interpretation": "All three direct state writes read back exactly as requested, so the patch reached the intended raw storage cells. The counterfactual still reverts before protected harm observation with token0 custom error DebtOverflow, wrapped by the pair as TRANSFER_FAILED. Read-back validates mutation application, not the semantic claim that these cells fully model the no-helper state.",
        "causal_status": "INCONCLUSIVE_PRE_HARM_DEBT_OVERFLOW_SEMANTICS_PENDING",
        "unresolved": [
            "Resolve DebtOverflow argument meanings from token0 runtime semantics/source.",
            "Confirm that the patched token balance cells are the complete state required by the token debt invariant.",
            "Do not promote the pre-harm revert to SUPPORTED_ROOT without those checks.",
        ],
        "raw_sha256": hashlib.sha256(RAW.read_bytes()).hexdigest(),
    }
    OUT.write_text(json.dumps(out, indent=2) + "\n")
    print(OUT)
    print(hashlib.sha256(OUT.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()

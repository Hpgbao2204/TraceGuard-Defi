#!/usr/bin/env python3
"""Materialize the VETH four-cell coupled-state patch result.

This artifact distinguishes successful state application from a causal result.
The fourth cell is the VirtualToken accounting/debt-like state written by the
virtual-liquidity helper; its semantic label remains conservative.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "eval/results/e5_rcfh/veth_buyquote_dose_probe/settlement_entry_storage_patch_real_four_cells.json"
OUT = ROOT / "eval/results/e5_rcfh/veth_buyquote_dose_probe/settlement_entry_storage_patch_four_cells_audit.json"

FOURTH_SLOT = "0xcdce3b4e6758f9ae9dbf97b1b5bd59c473cd561344fd70eb643587c9149798e4"
PRE_HELPER = "0x000000000000000000000000000000000000000000000001158e460913d00000"
HELPER_VALUE = "0x00000000000000000000000000000000000000000000001158e460913d000000"


def main() -> None:
    data = json.loads(RAW.read_text())
    target = data["per_tx"][57]
    intervention = target["call_intervention"]
    patches = intervention["storage_patches"]
    readback_pass = len(patches) == 4 and all(p["after"] == p["read_back"] for p in patches)
    fourth = next((p for p in patches if p["slot"].lower().endswith(FOURTH_SLOT[2:])), None)
    if fourth is None:
        raise ValueError("fourth VirtualToken accounting slot is missing")
    if fourth["after"].lower() != PRE_HELPER.lower():
        raise ValueError("fourth slot was not patched to the authenticated pre-helper value")

    out = {
        "status": "FOUR_CELL_PATCH_READBACK_PASS_PRE_HARM_INSUFFICIENT_BALANCE",
        "case_id": "defihacklabs-veth-2024-11-14",
        "trigger": {
            "caller": intervention["caller"],
            "callee": intervention["callee"],
            "selector": intervention["selector"],
            "depth": intervention["depth"],
            "trace_role": "settlement_entry_before_reverse_swap",
        },
        "coupled_state": {
            "patch_count": len(patches),
            "all_after_equals_read_back": readback_pass,
            "fourth_slot": {
                "address": fourth["address"],
                "slot": fourth["slot"],
                "semantic_label": "VirtualToken helper-updated accounting/debt-like state; exact source-level name unresolved",
                "authenticated_pre_helper_value": PRE_HELPER,
                "helper_written_value": HELPER_VALUE,
                "patch_before": fourth["before"],
                "patch_after": fourth["after"],
                "patch_read_back": fourth["read_back"],
            },
            "scope": "pair packed reserve, token0 balanceOf(pair), token1 balanceOf(pair), and helper-updated VirtualToken accounting cell",
        },
        "execution": {
            "actual_status": target["actual_status"],
            "actual_gas": target["actual_gas"],
            "status_match": target["status_match"],
            "gas_match": target["gas_match"],
            "logs_match": target["logs_match"],
            "post_state_match": target["post_state_match"],
            "prestate_proof_verified": data["prestate_proof_verified"],
            "proof_accounts_verified": data["proof_accounts_verified"],
            "proof_storage_cells_verified": data["proof_storage_cells_verified"],
        },
        "intervention": {
            "application_verified": intervention["application_verified"],
            "match_count": intervention["match_count"],
            "first_revert_depth": intervention["first_revert_depth"],
            "first_revert_data": intervention["first_revert_data"],
            "revert_class": "INSUFFICIENT_BALANCE_FOR_TRANSFER",
            "revert_phase": "pre_harm_downstream_transfer",
            "storage_patches": patches,
        },
        "comparison_to_three_cell_patch": {
            "three_cell_result": "DebtOverflow(address,uint256,uint256) at token0 transfer path",
            "four_cell_result": "generic insufficient balance for transfer before harm",
            "interpretation": "Adding the helper-updated accounting cell removes the prior DebtOverflow, showing that error depended on coupled accounting state. The remaining transfer failure shows the four-cell state is still not a complete executable no-helper counterfactual.",
        },
        "interpretation": "The fourth coupled state cell is directly supported by authenticated pre/post state and helper-window SSTORE telemetry. All four writes were applied and read back exactly. The replay nevertheless reverts before protected harm observation, so this is a state-mapping finding, not causal support for the timing hypothesis.",
        "causal_status": "INCONCLUSIVE_PRE_HARM_COUPLED_STATE_INCOMPLETE",
        "unresolved": [
            "Identify the exact source and operands of the remaining insufficient-balance transfer failure.",
            "Determine whether another VirtualToken/accounting cell or a downstream amount dependency must be modeled.",
            "Do not promote this result to SUPPORTED_ROOT or SUPPORTED_ROOT_BLOCKING.",
        ],
        "raw_sha256": hashlib.sha256(RAW.read_bytes()).hexdigest(),
    }
    OUT.write_text(json.dumps(out, indent=2) + "\n")
    print(OUT)
    print(hashlib.sha256(OUT.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()

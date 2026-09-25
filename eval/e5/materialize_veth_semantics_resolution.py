"""Materialize the VETH semantic-resolution checkpoint from verified reads."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "eval/results/e5_rcfh/veth_buyquote_dose_probe/semantics_resolution.json"


def main() -> None:
    OUT.write_text(json.dumps({
        "schema_version": 1,
        "artifact": "e5-veth-semantics-resolution",
        "case_id": "defihacklabs-veth-2024-11-14",
        "historical_block": 21184784,
        "verified_rpc_reads": {
            "pair": "0x582d17d24127cfdcbc8c4e0a40c12d77b2e7a48d",
            "token0": "0x280a8955a11fcd81d72ba1f99d265a48ce39ac2e",
            "token1": "0xab181941a6096296ecf1b0859ea65c797676d428",
            "token0_decimals": 18,
            "token1_decimals": 18,
            "source": "archive eth_call at historical block",
        },
        "etherscan_v2_source_lookup": {
            "pair_contract_name": "UniswapV2Pair",
            "token0_contract_name": "VirtualToken",
            "token1_contract_name": "LamboToken",
            "source_lookup_status": "VERIFIED_CURRENT_SOURCE_RETURNED",
            "historical_runtime_equivalence": "NOT_REPROVEN_BY_THIS_ARTIFACT",
        },
        "trace_observations_dose_100": {
            "swap_calldata_amount1_out_raw": "79671143501326690348133279",
            "swap_event_amount1_out_raw": "79671143501326690348133279",
            "token1_transfer_pair_to_attacker_raw": "79671143501326690348133279",
            "token1_balanceOf_pair_after_funding_raw": "368252217875907560863761",
            "reported_getReserves_token1_raw": "80039395719202597908997040",
        },
        "classification": "SEMANTICS_RESOLVED_STANDARD_AMM_PATH",
        "conclusion": (
            "Decimals and token order are not the source of the discrepancy. "
            "The swap calldata argument is separate from the committed output: "
            "the pair Swap event and token Transfer agree. Preserving the trailing "
            "hexadecimal zero in reserve1 makes standard UniswapV2 getAmountOut "
            "match the committed output, and post-transfer balance plus output "
            "reconstructs reserve1. The apparent anomaly was an analyzer parsing "
            "error, not an unexplained protocol effect."
        ),
        "next_required": [
            "retain the corrected reserve parser as a regression test",
            "keep calldata, event output, and Transfer output as separate fields",
            "recompute dose-response using the corrected raw-unit values",
        ],
    }, indent=2) + "\n")
    print(OUT)


if __name__ == "__main__":
    main()

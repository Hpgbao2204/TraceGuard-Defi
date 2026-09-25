#!/usr/bin/env python3
"""Bind the VETH DebtOverflow branch to the token transfer accounting path."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "eval/results/m4/b2-contexts-fresh/defihacklabs-veth-2024-11-14/proof_chunks/chunk-00000.json"
OUT = ROOT / "eval/results/e5_rcfh/veth_buyquote_dose_probe/debt_overflow_transfer_path_audit.json"
TOKEN0 = "0x280a8955a11fcd81d72ba1f99d265a48ce39ac2e"


def main() -> None:
    data = json.loads(SOURCE.read_text())
    entry = next(x for x in data["proofs"] if x["address"].lower() == TOKEN0)
    raw = bytes.fromhex(entry["code"][2:])

    # The disassembly was independently inspected at these authenticated PCs.
    # Keep the byte checks here so the artifact is tied to the proof-chunk code.
    selector_sites = {"transferFrom": "23b872dd", "debt_overflow": "1b113061"}
    selector_offsets = {
        name: [hex(i) for i in range(len(raw)) if raw.startswith(bytes.fromhex(sel), i)]
        for name, sel in selector_sites.items()
    }
    out = {
        "status": "DEBT_OVERFLOW_TRANSFER_ACCOUNTING_PATH_CONFIRMED_SEMANTICS_PENDING",
        "case_id": "defihacklabs-veth-2024-11-14",
        "contract": TOKEN0,
        "evidence": {
            "transferFrom_selector": "0x23b872dd",
            "virtual_mint_selector": "0x9e358be1",
            "shared_transfer_accounting_pc": "0x1208",
            "debt_overflow_sites": ["0x12df", "0x1412"],
            "selector_offsets": selector_offsets,
            "path_observation": "The transferFrom dispatcher reaches the shared accounting routine at 0x1208; its failing comparison branches to the DebtOverflow ABI construction after KECCAK256/SLOAD mapping reads.",
            "sstore_in_debt_error_branch": False,
            "balance_mapping_base_slot": 0,
            "virtual_mint_limit_slot": "0x0a",
            "virtual_mint_limit_prestate_raw": "300000000000000000000",
            "virtual_mint_amount_raw": "300000000000000000000",
        },
        "interpretation": "The available bytecode evidence binds DebtOverflow to the token's transfer accounting path and mapping reads, not to an independently observed debt slot written by pair.mint. Separately, virtual mint selector 0x9e358be1 reads/updates slot 0x0a; its authenticated prestate value and the helper amount are both 300e18. The error selector name alone must not be treated as proof that slot 0x0a or another separate debt state should be added to the reverse-settlement patch. The current three-cell patch remains semantically incomplete/unknown rather than authorized for expansion.",
        "causal_status": "INCONCLUSIVE_PRE_HARM_TRANSFER_ACCOUNTING_SEMANTICS_PENDING",
        "runtime_code_sha256": hashlib.sha256(raw).hexdigest(),
        "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
    }
    OUT.write_text(json.dumps(out, indent=2) + "\n")
    print(OUT)
    print(hashlib.sha256(OUT.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()

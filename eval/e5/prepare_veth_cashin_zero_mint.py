#!/usr/bin/env python3
"""Prepare a narrow historical runtime patch for the VETH cashIn path.

At PC 0x0c60 the observed native cashIn branch executes CALLVALUE before
calling mint helper 0x1193. Replacing CALLVALUE (0x34) with PUSH0 (0x5f)
forces the helper's amount argument to zero while preserving code size and
the surrounding control flow. This is a diagnostic root-boundary probe only.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASE = ROOT / "eval/results/m4/b2-contexts-fresh/defihacklabs-veth-2024-11-14"
OUT_CODE = ROOT / "eval/results/e5_rcfh/veth_buyquote_dose_probe/veth_token_cashin_zero_mint.runtime.hex"
OUT_META = ROOT / "eval/results/e5_rcfh/veth_buyquote_dose_probe/cashin_zero_mint_patch.json"
TOKEN = "0x280a8955a11fcd81d72ba1f99d265a48ce39ac2e"
PC = 0x0C60

def main():
    d = json.loads((CASE / "prestates.json").read_text())
    original = d[57]["trace"][TOKEN]["code"]
    raw = bytearray.fromhex(original[2:])
    assert raw[PC] == 0x34, hex(raw[PC])
    raw[PC] = 0x5F  # PUSH0: mint helper receives amount 0 instead of CALLVALUE
    patched = "0x" + raw.hex()
    OUT_CODE.parent.mkdir(parents=True, exist_ok=True)
    OUT_CODE.write_text(patched + "\n")
    meta = {
        "status": "READY_FOR_DIAGNOSTIC_REPLAY",
        "target": TOKEN,
        "source": "eval/results/m4/b2-contexts-fresh/defihacklabs-veth-2024-11-14/prestates.json#/57/trace/" + TOKEN,
        "patch": {"pc_hex": "0x0c60", "original_opcode": "CALLVALUE", "patched_opcode": "PUSH0", "purpose": "force observed native cashIn mint amount to zero"},
        "original_code_sha256": hashlib.sha256(bytes.fromhex(original[2:])).hexdigest(),
        "patched_code_sha256": hashlib.sha256(bytes(raw)).hexdigest(),
        "scope": "diagnostic only; historical runtime override; not a deployed patch and not causal verdict by itself",
        "limitation": "The patch tests a zero-mint boundary, not a semantically validated fair-collateral policy.",
    }
    OUT_META.write_text(json.dumps(meta, indent=2) + "\n")
    print(OUT_CODE)
    print(OUT_META)
    print(meta["patched_code_sha256"])

if __name__ == "__main__":
    main()

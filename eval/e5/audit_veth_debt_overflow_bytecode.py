#!/usr/bin/env python3
"""Record the static bytecode evidence around VETH's 0x1b113061 error."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "eval/results/m4/b2-contexts-fresh/defihacklabs-veth-2024-11-14/proof_chunks/chunk-00000.json"
OUT = ROOT / "eval/results/e5_rcfh/veth_buyquote_dose_probe/debt_overflow_bytecode_audit.json"
TOKEN0 = "0x280a8955a11fcd81d72ba1f99d265a48ce39ac2e"
SELECTOR = "1b113061"


def main() -> None:
    data = json.loads(SOURCE.read_text())
    code = None
    for account in data.get("proofs", []):
        if account.get("address", "").lower() == TOKEN0:
            code = account.get("code")
            break
    if code is None:
        text = SOURCE.read_text()
        marker = f'"{TOKEN0}":'
        pos = text.lower().find(marker)
        if pos >= 0:
            code = json.loads(text[pos + len(marker):].split(",\n", 1)[0])
    if not code:
        raise SystemExit("token0 runtime code not found in proof chunk")
    raw = bytes.fromhex(code[2:] if code.startswith("0x") else code)
    offsets = []
    needle = bytes.fromhex(SELECTOR)
    start = 0
    while True:
        at = raw.find(needle, start)
        if at < 0:
            break
        offsets.append(hex(at))
        start = at + 1

    out = {
        "status": "BYTECODE_READ_SIDE_CHECK_FOUND_DEBT_OVERFLOW_SEMANTICS_PENDING",
        "case_id": "defihacklabs-veth-2024-11-14",
        "contract": TOKEN0,
        "selector": "0x" + SELECTOR,
        "signature_lookup": "DebtOverflow(address,uint256,uint256)",
        "runtime_code_sha256": hashlib.sha256(raw).hexdigest(),
        "selector_byte_offsets": offsets,
        "disassembly_sites": ["0x12df", "0x1412"],
        "observed_shape": {
            "before_revert": "KECCAK256 -> SLOAD -> PUSH4 0x1b113061 -> ABI encode 3 words -> REVERT",
            "sstore_in_immediate_error_branch": False,
            "balance_of_getter_mapping_base": "slot 0 is evidenced by the balanceOf getter path at PC 0x0756",
        },
        "interpretation": "The error path performs a mapping read and then reverts; the local branch contains no SSTORE. This is evidence of a read-side invariant/check, not proof of a separate debt slot written by pair.mint. The mapping's semantic identity and the meanings of arg1/arg2 remain unresolved.",
        "causal_status": "INCONCLUSIVE_PRE_HARM_DEBT_MAPPING_SEMANTICS_PENDING",
        "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
    }
    OUT.write_text(json.dumps(out, indent=2) + "\n")
    print(OUT)
    print(hashlib.sha256(OUT.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()

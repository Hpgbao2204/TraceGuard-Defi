"""Materialize the wrapper runtime with a frozen shadow implementation address."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ARTIFACT = ROOT / "out/MureDistributionContractSignerGuard.sol/MureDistributionContractSignerGuard.json"
OUT = ROOT / "mure_guard_runtime.bin"
SHADOW = "0x000000000000000000000000000000000000f1a3"


def main() -> None:
    artifact = json.loads(ARTIFACT.read_text())
    code = bytearray.fromhex(artifact["deployedBytecode"]["object"][2:])
    refs = artifact["deployedBytecode"]["immutableReferences"]["4"]
    value = bytes.fromhex(SHADOW[2:].rjust(64, "0"))
    for ref in refs:
        code[ref["start"]:ref["start"] + ref["length"]] = value
    OUT.write_text("0x" + code.hex() + "\n")
    print(json.dumps({"output": str(OUT), "shadow": SHADOW, "bytes": len(code)}))


if __name__ == "__main__":
    main()

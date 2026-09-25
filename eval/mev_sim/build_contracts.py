"""Compile the simulation contracts into ``contracts/artifacts.json`` (committed).

Only needed after editing ``contracts/src/*.sol``. Requires solc 0.8.24:
    SOLC=/path/to/solc python -m eval.mev_sim.build_contracts
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "contracts" / "src"
OUT = HERE / "contracts" / "artifacts.json"
CONTRACTS = ("SimToken", "SimPair", "SimRouter", "SimAggregator")


def main() -> None:
    solc = os.environ.get("SOLC", "solc")
    sources = {p.name: {"content": p.read_text()} for p in sorted(SRC.glob("*.sol"))}
    request = {
        "language": "Solidity",
        "sources": sources,
        "settings": {
            "optimizer": {"enabled": True, "runs": 200},
            "evmVersion": "cancun",
            "outputSelection": {"*": {"*": ["abi", "evm.bytecode.object"]}},
        },
    }
    proc = subprocess.run([solc, "--standard-json"], input=json.dumps(request),
                          capture_output=True, text=True, check=True)
    result = json.loads(proc.stdout)
    errors = [e for e in result.get("errors", []) if e["severity"] == "error"]
    if errors:
        raise SystemExit("\n".join(e["formattedMessage"] for e in errors))
    artifacts = {}
    for unit in result["contracts"].values():
        for name, c in unit.items():
            if name in CONTRACTS:
                artifacts[name] = {"abi": c["abi"], "bytecode": "0x" + c["evm"]["bytecode"]["object"]}
    version = subprocess.run([solc, "--version"], capture_output=True, text=True).stdout.split()[-1]
    OUT.write_text(json.dumps({"solc": version, "contracts": artifacts}, indent=1, sort_keys=True) + "\n")
    print(f"wrote {OUT} ({', '.join(sorted(artifacts))})")


if __name__ == "__main__":
    main()

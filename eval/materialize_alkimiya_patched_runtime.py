"""Copy historical immutable values into the patched SilicaPools runtime."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--original-artifact", required=True)
    ap.add_argument("--patched-artifact", required=True)
    ap.add_argument("--historical-runtime", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    original = json.loads(Path(args.original_artifact).read_text())
    patched = json.loads(Path(args.patched_artifact).read_text())
    historical = bytes.fromhex(Path(args.historical_runtime).read_text().strip()[2:])
    # Solidity preserves the compiler's immutable-reference ordering across
    # this source-only patch, while byte offsets shift after the inserted
    # guard.  Preserve JSON/compiler order; offset-sorting can pair distinct
    # inherited EIP-712 immutables and change pool hashes.
    original_refs = [
        (r["start"], r["length"])
        for refs in original["deployedBytecode"]["immutableReferences"].values()
        for r in refs
    ]
    patched_refs = [
        (r["start"], r["length"])
        for refs in patched["deployedBytecode"]["immutableReferences"].values()
        for r in refs
    ]
    if len(original_refs) != len(patched_refs):
        raise SystemExit("immutable reference count changed")
    runtime = bytearray.fromhex(patched["deployedBytecode"]["object"][2:])
    if len(historical) != len(bytes.fromhex(original["deployedBytecode"]["object"][2:])):
        raise SystemExit("historical runtime length mismatch")
    for (src, length), (dst, patched_length) in zip(original_refs, patched_refs):
        if length != patched_length:
            raise SystemExit("immutable length changed")
        runtime[dst:dst + length] = historical[src:src + length]
    out = "0x" + runtime.hex()
    Path(args.output).write_text(out + "\n")
    print(json.dumps({"bytes": len(runtime), "immutable_regions": patched_refs,
                      "output": args.output}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

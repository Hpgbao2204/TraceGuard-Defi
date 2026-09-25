"""Build a clearly labelled synthetic safe-argument control for the Alkimiya probe."""

from __future__ import annotations

import json
import sys
from pathlib import Path


CONTEXT = Path("eval/results/m6/dependency-contexts/alkimiya")
OUT = Path("eval/results/e5_rcfh/alkimiya_safe_control_calldata.txt")
OVERFLOW = f"{(1 << 128) + 1:064x}"


def main() -> None:
    txs = json.loads((CONTEXT / "transactions.json").read_text())
    if len(txs) != 1:
        raise SystemExit(f"expected one target transaction, got {len(txs)}")
    data = (txs[0].get("input") or txs[0].get("data") or "").lower()
    occurrences = data.count(OVERFLOW)
    if occurrences != 1:
        raise SystemExit(f"expected exactly one overflow word, got {occurrences}")
    safe_value = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    if not 0 <= safe_value <= (1 << 128) - 1:
        raise SystemExit("safe value must fit uint128")
    safe = data.replace(OVERFLOW, f"{safe_value:064x}", 1)
    OUT.write_text(safe + "\n")
    print(json.dumps({"output": str(OUT), "replaced_words": occurrences,
                      "control_kind": "SYNTHETIC_SAFE_ARGUMENT"}))


if __name__ == "__main__":
    main()

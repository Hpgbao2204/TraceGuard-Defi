"""Re-acquire the 256 ancestor headers of a B2 context from a public JSON-RPC endpoint.

    python -m eval.revision.refetch_ancestors eval/results/m6/dependency-contexts/alkimiya

Some local contexts lost ``ancestors.json`` when large files were pruned. Headers are public, so they
are fetched without credentials, checked for a contiguous hash chain ending at the target block's
parent, and the parent's state root is checked against the root the context's proofs verify against.
"""
from __future__ import annotations

import argparse
import time
import json
import urllib.request
from pathlib import Path

from eval.results.b2_context import _validate_ancestor_headers

DEFAULT_RPCS = ("https://rpc.flashbots.net", "https://ethereum-rpc.publicnode.com", "https://eth.llamarpc.com")
CACHE = Path(__file__).resolve().parents[2] / ".cache" / "revision" / "headers"


def _post(rpc: str, number: int) -> dict:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "eth_getBlockByNumber",
                       "params": [hex(number), False]}).encode()
    req = urllib.request.Request(rpc, body, {"Content-Type": "application/json", "User-Agent": "b2-ancestors"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read()).get("result")
    if not isinstance(result, dict) or not result.get("hash"):
        raise ValueError("empty header")
    return result


def _header(rpcs: list[str], number: int) -> dict:
    """One header, cached on disk; rotates endpoints and backs off on rate limits."""
    path = CACHE / f"{number}.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    delay = 1.0
    for attempt in range(12):
        rpc = rpcs[attempt % len(rpcs)]
        try:
            header = _post(rpc, number)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(header), encoding="utf-8")
            time.sleep(0.25)
            return header
        except Exception:  # rate limit, timeout or empty result: try the next endpoint after a pause
            time.sleep(delay)
            delay = min(delay * 2, 30.0)
    raise SystemExit(f"header {number} unavailable from {rpcs}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("context", type=Path)
    ap.add_argument("--rpc", action="append", default=[])
    args = ap.parse_args()
    block = json.loads((args.context / "block.json").read_text(encoding="utf-8"))
    number = int(block["number"], 16)
    wanted = list(range(number - 1, max(-1, number - 257), -1))
    headers: list[dict] = []
    for n in wanted:
        headers.append(_header(args.rpc or list(DEFAULT_RPCS), n))
    _validate_ancestor_headers(block, headers)
    pm = json.loads((args.context / "proof_manifest.json").read_text(encoding="utf-8"))
    if headers[0]["stateRoot"].lower() != pm["state_root"].lower():
        raise SystemExit("parent state root differs from the root the proofs verify against")
    (args.context / "ancestors.json").write_text(json.dumps(headers, indent=1), encoding="utf-8")
    print(f"wrote {len(headers)} headers; parent {headers[0]['number']} state root matches the proofs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

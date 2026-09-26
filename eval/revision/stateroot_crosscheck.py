"""Cross-check the state roots that the replay proofs verify against with independent providers.

    python -m eval.revision.stateroot_crosscheck --out .cache/revision/stateroot.json

For every fixed-20 context (``eval/results/m4/b2-contexts-fresh``) the proofs were fetched from one
archive endpoint and verified against ``state_root`` of ``state_block`` (``proof_manifest.json``). This
script asks each independent JSON-RPC endpoint for the header of ``state_block`` and of the target block
and checks that the state root, the target block hash, and the parent link agree with the context.
Only public block headers are requested; no key is needed.
"""
from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTEXTS = ROOT / "eval" / "results" / "m4" / "b2-contexts-fresh"
DEFAULT_RPCS = ("https://ethereum-rpc.publicnode.com", "https://eth.llamarpc.com", "https://rpc.flashbots.net")


def header(rpc: str, number: int) -> dict:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "eth_getBlockByNumber",
                       "params": [hex(number), False]}).encode()
    req = urllib.request.Request(rpc, body, {"Content-Type": "application/json", "User-Agent": "stateroot-check"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())["result"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--contexts", type=Path, default=CONTEXTS)
    ap.add_argument("--rpc", action="append", default=[], help="independent endpoint (repeatable)")
    ap.add_argument("--out", type=Path, default=ROOT / ".cache" / "revision" / "stateroot.json")
    args = ap.parse_args()
    rpcs = args.rpc or list(DEFAULT_RPCS)
    rows = []
    for ctx in sorted(p for p in args.contexts.iterdir() if (p / "proof_manifest.json").is_file()):
        pm = json.loads((ctx / "proof_manifest.json").read_text(encoding="utf-8"))
        blk = json.loads((ctx / "block.json").read_text(encoding="utf-8"))
        sb, root = int(pm["state_block"]), pm["state_root"].lower()
        row = {"case": ctx.name, "state_block": sb, "state_root": root, "providers": {}}
        for rpc in rpcs:
            try:
                parent, target = header(rpc, sb), header(rpc, int(blk["number"], 16))
                row["providers"][rpc] = {
                    "state_root_match": parent["stateRoot"].lower() == root,
                    "target_hash_match": target["hash"].lower() == blk["hash"].lower(),
                    "parent_link_match": target["parentHash"].lower() == parent["hash"].lower(),
                }
            except Exception as exc:  # an endpoint that fails is reported, never counted as a match
                row["providers"][rpc] = {"error": f"{type(exc).__name__}: {exc}"}
        ok = [v for v in row["providers"].values() if "error" not in v]
        row["agree_all"] = bool(ok) and all(all(v.values()) for v in ok)
        row["n_providers_ok"] = len(ok)
        rows.append(row)
        print(f"{ctx.name:55s} providers={len(ok)} agree={row['agree_all']}")
    summary = {"n_cases": len(rows), "all_agree": sum(r["agree_all"] for r in rows),
               "min_providers": min((r["n_providers_ok"] for r in rows), default=0), "rpcs": rpcs}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

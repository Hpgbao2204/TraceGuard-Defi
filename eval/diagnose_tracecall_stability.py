"""Compare one exact debug_traceCall JSON body across repeated raw requests."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import urllib.request

from core.env import load_dotenv
from core.rpc import RpcClient
from eval.tracecall_override import _call_object


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tx", required=True)
    ap.add_argument("--block", type=int, required=True)
    ap.add_argument("--tx-index", type=int, required=True)
    ap.add_argument("--rpc-env", default="QUICKNODE_TRACE_RPC")
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    load_dotenv()
    rpc = os.environ[args.rpc_env]
    client = RpcClient(rpc, timeout=45, attempts=1)
    tx = client.eth_get_transaction(args.tx)
    body = {
        "jsonrpc": "2.0", "id": 1, "method": "debug_traceCall",
        "params": [_call_object(tx), hex(args.block),
                   {"tracer": "callTracer", "timeout": "30s",
                    "txIndex": hex(args.tx_index)}],
    }
    raw = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode()
    body_sha = hashlib.sha256(raw).hexdigest()
    observations = []
    for i in range(args.repeats):
        started = time.monotonic()
        req = urllib.request.Request(rpc, data=raw, method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=45) as response:
                result = json.loads(response.read())
            trace = result.get("result") or {}
            observations.append({"attempt": i + 1, "elapsed_ms": round((time.monotonic() - started) * 1000),
                                 "error": trace.get("error"), "gasUsed": trace.get("gasUsed"),
                                 "failed": trace.get("failed"), "output": trace.get("output"),
                                 "rpc_error": result.get("error")})
        except Exception as exc:
            observations.append({"attempt": i + 1, "error": str(exc)[:512]})
    out = {"tx": args.tx, "block": args.block, "tx_index": args.tx_index,
           "request_sha256": body_sha, "request_bytes": len(raw),
           "request": body, "raw_repeats": observations}
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2); f.write("\n")
    print(json.dumps({"request_sha256": body_sha, "raw_repeats": observations}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

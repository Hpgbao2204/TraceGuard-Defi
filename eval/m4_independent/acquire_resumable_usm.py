"""Resumable USM context acquisition; writes one complete record per tx."""
import json, sys, time
from pathlib import Path
from core.env import load_dotenv, resolve_rpc, resolve_trace_rpc
from core.rpc import RpcClient

ROOT = Path(__file__).parents[2]
TX = "0xfae5e751b8ce01457cbb6b529839f24a0cff50faaabcbd0fd02ca0cf559b050e"
BLOCK, INDEX = 25716150, 1193
OUT = ROOT / "eval/results/m4/usm-cache-v3"
OUT.mkdir(parents=True, exist_ok=True)

def write(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")

def main():
    load_dotenv()
    archive = RpcClient(resolve_rpc("mainnet"), timeout=90, attempts=2)
    trace = RpcClient(resolve_trace_rpc("mainnet"), timeout=120, attempts=2)
    block = archive.call("eth_getBlockByNumber", [hex(BLOCK), True])
    txs = block.get("transactions", [])[:INDEX + 1]
    if txs[INDEX].get("hash", "").lower() != TX:
        raise SystemExit("USM frozen transaction identity mismatch")
    write(OUT / "manifest.json", {"schema_version": 3, "tx_hash": TX, "block": BLOCK,
        "tx_index": INDEX, "count_expected": len(txs), "archive_provider": archive.url,
        "trace_provider": trace.url, "status": "in_progress"})
    for i, tx in enumerate(txs):
        path = OUT / f"tx_{i:04d}.json"
        if path.is_file():
            continue
        h = tx["hash"]
        receipt = archive.eth_get_receipt(h)
        pre = trace.call("debug_traceTransaction", [h, {"tracer":"prestateTracer"}])
        call = trace.call("debug_traceTransaction", [h, {"tracer":"callTracer"}])
        post = trace.call("debug_traceTransaction", [h, {"tracer":"prestateTracer", "tracerConfig":{"diffMode":True}}])
        write(path, {"schema_version":3, "index":i, "tx_hash":h, "transaction":tx,
            "receipt":receipt, "prestate":pre, "calltrace":call, "poststate":post})
        write(OUT / "progress.json", {"schema_version":3, "next_index":i+1,
            "complete_count":i+1, "expected_count":len(txs), "updated_at":time.time()})
        if i % 10 == 0 or i == len(txs)-1:
            print(f"{i+1}/{len(txs)}", flush=True)
    write(OUT / "manifest.json", {"schema_version":3, "tx_hash":TX, "block":BLOCK,
        "tx_index":INDEX, "count_expected":len(txs), "count_complete":len(list(OUT.glob('tx_*.json'))),
        "archive_provider":archive.url, "trace_provider":trace.url, "status":"complete"})
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

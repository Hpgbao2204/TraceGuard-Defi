"""Acquire transaction metadata for the 80-case DeFiHackLabs candidate pool."""
from __future__ import annotations
import json, time
import argparse
from pathlib import Path
from core.env import load_dotenv, resolve_rpc
from core.rpc import RpcClient, RpcError

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "eval/results/e5_rcfh/defihacklabs_t0_candidate_pool.json"
OUT = ROOT / "eval/results/e5_rcfh/defihacklabs_replay_acquisition.json"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end", type=int, default=None)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    load_dotenv()
    rpc_url = resolve_rpc("ethereum")
    if not rpc_url:
        raise SystemExit("archive RPC unavailable")
    rpc = RpcClient(rpc_url, timeout=30, attempts=2)
    src = json.loads(SRC.read_text())
    rows = []
    selected = src["candidates"][args.start:args.end]
    for i, c in enumerate(selected, args.start + 1):
        tx_hash = c["transaction"]["tx_hashes"][0].lower()
        row = {"candidate_id": c["candidate_id"], "tx_hash": tx_hash, "chain": c["transaction"]["chain"], "status": "UNKNOWN"}
        try:
            tx = rpc.eth_get_transaction(tx_hash)
            receipt = rpc.eth_get_receipt(tx_hash)
            if not tx or not receipt:
                row.update(status="NOT_FOUND", reason="transaction_or_receipt_missing")
            else:
                block = int(tx["blockNumber"], 16)
                row.update(status="READY_FOR_B2", block=block, tx_index=int(tx["transactionIndex"], 16),
                           mainnet_gas=int(receipt["gasUsed"], 16), tx_status=int(receipt["status"], 16),
                           sender=tx.get("from"), to=tx.get("to"), value=tx.get("value"))
        except Exception as exc:  # retain classification without credentials
            msg = str(exc).lower()
            kind = "dns" if any(x in msg for x in ("resolve", "name or service")) else "transport" if any(x in msg for x in ("timeout", "connection")) else "jsonrpc_provider"
            row.update(status="ACQUISITION_ERROR", error_kind=kind, error=str(exc).split("?", 1)[0])
        rows.append(row)
        print(f"[{i}/{len(src['candidates'])}] {c['candidate_id']} -> {row['status']}", flush=True)
        time.sleep(0.1)
    summary = {}
    for r in rows: summary[r["status"]] = summary.get(r["status"], 0) + 1
    out = {"schema_version": 1, "artifact": "defihacklabs-replay-acquisition-v1", "source_artifact": str(SRC.relative_to(ROOT)), "rpc_role": "archive_transaction_metadata_only", "range": [args.start, args.end], "cases": rows, "summary": summary, "next": "run B2 only for READY_FOR_B2; no missing/error case is treated as NO_HARM"}
    out_path = args.out or OUT
    out_path.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2))

if __name__ == "__main__": main()

"""Acquire proof-bound B2 contexts for the Ethereum subset of the new queue."""
import json
from pathlib import Path
from core.env import load_dotenv, resolve_rpc_candidates, resolve_trace_rpc_candidates
from core.rpc import RpcClient
from eval.results.b2_context import acquire as acquire_context
from eval.b2_proofs import acquire as acquire_proofs

ROOT = Path(__file__).resolve().parents[1]
CASES = {
    "Dough Finance": ("0x92cdcc732eebf47200ea56123716e337f6ef7d5ad714a2295794fdc6031ebb2e", 20288623),
    "XPEPE": ("0xbdec39a74e620fc624f90483aff067b17044f81138e6c30038daf7f873159db4", 21699659),
    "Euler Finance": ("0xc310a0affe2169d1f6feec1c63dbc7f7c62a887fa48795d327d4d2da2d6b111d", 16817996),
    "Indexed Finance": ("0x44aad3b853866468161735496a5d9cc961ce5aa872924c5d78673076b1cd95aa", 13417949),
    "Harvest Finance": ("0x35f8d2f572fceaac9288e5d462117850ef2694786992a8c3f6d02612277b0877", 11129474),
    "KyberSwap Elastic": ("0x396a83df7361519416a6dc960d394e689dd0f158095cbc6a6c387640716f5475", 18630409),
}

def main():
    load_dotenv()
    archive_urls = resolve_rpc_candidates("mainnet")
    trace_urls = resolve_trace_rpc_candidates("mainnet")
    archive = RpcClient(archive_urls[0], timeout=60, attempts=2, fallback_urls=archive_urls[1:])
    trace = RpcClient(trace_urls[0], timeout=60, attempts=2, fallback_urls=trace_urls[1:])
    results = []
    for name, (tx_hash, expected_block) in CASES.items():
        tx = archive.eth_get_transaction(tx_hash)
        rec = archive.eth_get_receipt(tx_hash)
        if not tx or not rec:
            results.append({"name": name, "status": "BLOCKED_RPC_CONTEXT_UNAVAILABLE"})
            continue
        block = int(tx["blockNumber"], 16)
        tx_index = int(tx["transactionIndex"], 16)
        slug = name.lower().replace(" ", "-")
        out = ROOT / "eval/results/runs" / f"b2-context-flashloan-{slug}-{block}"
        try:
            if not (out / "prestates.json").is_file():
                acquire_context(archive, trace, tx_hash=tx_hash, block_number=block,
                                tx_index=tx_index, out=out, timeout_s=90.0)
                acquire_proofs(out, archive)
            results.append({"name": name, "status": "B2_CONTEXT_ACQUIRED", "tx_hash": tx_hash,
                            "block": block, "tx_index": tx_index, "context": str(out.relative_to(ROOT))})
        except Exception as exc:
            results.append({"name": name, "status": "B2_CONTEXT_ACQUISITION_FAILED",
                            "error_type": type(exc).__name__, "block": block, "tx_index": tx_index})
    p = ROOT / "eval/results/m6_flashloan_b2_context_acquisition.json"
    p.write_text(json.dumps({"schema_version":1,"scope":"supplementary; context acquisition only","cases":results}, indent=2)+"\n")
    print(json.dumps(results, indent=2))
if __name__ == "__main__": main()

"""Read-only first B2 screen for xSNXa; no context or verdict mutation."""
from __future__ import annotations
import json
from pathlib import Path
from core.env import load_dotenv, resolve_rpc, resolve_trace_rpc
from core.rpc import RpcClient

TX = "0x7cc7d935d895980cdd905b2a134597fb91004b5d551d6db0fb265e3d9840da22"
XSNXA = "0xc5ac25cfc2b8284e84ca47dad21cf1319f732c11"
XSNXA_TOKEN = "0x2367012ab9c3da91290f71590d5ce217721eefe4"
POOL_CANDIDATE = "0x7cd5e2d0056a7a7f09cbb86e540ef4f6dccc97dd"
ROOT = Path(__file__).resolve().parents[2]

def main() -> int:
    load_dotenv()
    archive_url = resolve_rpc("mainnet")
    trace_url = resolve_trace_rpc("mainnet") or archive_url
    if not archive_url:
        raise SystemExit("ARCHIVE_RPC not configured")
    archive = RpcClient(archive_url, timeout=45, attempts=1)
    trace = RpcClient(trace_url, timeout=45, attempts=1)
    tx = archive.call("eth_getTransactionByHash", [TX])
    receipt = archive.call("eth_getTransactionReceipt", [TX])
    block = archive.call("eth_getBlockByNumber", [hex(12419918), True])
    traced = trace.call("debug_traceTransaction", [TX, {"tracer": "prestateTracer", "tracerConfig": {"diffMode": True}}])
    calls = trace.call("debug_traceTransaction", [TX, {"tracer": "callTracer", "tracerConfig": {"withLog": True}}])
    def acct(address):
        if isinstance(traced, dict) and isinstance(traced.get("pre"), dict):
            return {"pre": traced["pre"].get(address.lower()),
                    "post": (traced.get("post") or {}).get(address.lower())}
        return traced.get(address.lower(), {}) if isinstance(traced, dict) else {}
    if isinstance(traced, dict) and isinstance(traced.get("pre"), dict):
        account = acct(XSNXA)
    else:
        account = traced.get(XSNXA.lower(), {}) if isinstance(traced, dict) else {}
    frames = []
    value_frames = []
    def collect(frame):
        if not isinstance(frame, dict): return
        to = str(frame.get("to") or "").lower()
        value = frame.get("value")
        if value and isinstance(value, str) and int(value, 16) >= 10**18:
            value_frames.append({"type": frame.get("type"), "from": frame.get("from"), "to": to, "value": value})
        if to == XSNXA or str(frame.get("from") or "").lower() == XSNXA:
            frames.append({k: frame.get(k) for k in ("type", "from", "to", "value", "input", "output", "error")})
        for child in frame.get("calls") or []: collect(child)
    collect(calls)
    result = {
        "schema_version": 1,
        "status": "EXPLORATORY_RPC_PROBE_NOT_B2_CONTEXT",
        "case_id": "xtoken-xsnxa-2021-05-12",
        "tx_hash": TX,
        "target_block": 12419918,
        "tx_index": tx.get("transactionIndex") if isinstance(tx, dict) else None,
        "tx_to": tx.get("to") if isinstance(tx, dict) else None,
        "receipt_status": receipt.get("status") if isinstance(receipt, dict) else None,
        "block_tx_count": len(block.get("transactions", [])) if isinstance(block, dict) else None,
        "xsnxa_contract": XSNXA,
        "xsnxa_token_contract": XSNXA_TOKEN,
        "pool_candidate": POOL_CANDIDATE,
        "pool_candidate_state": acct(POOL_CANDIDATE),
        "pool_balance_window": {
            str(block_number): archive.call("eth_getBalance", [POOL_CANDIDATE, hex(block_number)])
            for block_number in (12419917, 12419918, 12419919, 12419920)
        },
        "role_code_lengths": {
            address: len(str(archive.call("eth_getCode", [address, hex(12419918)]))[2:]) // 2
            for address in (XSNXA, XSNXA_TOKEN, POOL_CANDIDATE)
        },
        "trace_top_level_keys": sorted(traced.keys()) if isinstance(traced, dict) else None,
        "xsnxa_prestate": account.get("pre"),
        "xsnxa_poststate": account.get("post"),
        "xsnxa_call_frames": frames,
        "nontrivial_value_frames": value_frames,
        "trace_observation": "prestateTracer diffMode account entry; requires independent normalization and proof-bound B2 context",
        "limitations": ["No Merkle proofs, ancestor context, replay, sham, or harm verdict was run."],
    }
    out = ROOT / "eval/exploratory/xtoken_xsnxa_rpc_probe.json"
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))

if __name__ == "__main__":
    main()

"""Probe XLoot implementation-code override on the historical transaction."""
from __future__ import annotations
import argparse, json
from pathlib import Path
from core.env import load_dotenv, resolve_trace_rpc
from core.rpc import RpcClient
from tracecall_override import trace_call, _call_object

TX = "0xab19752a450a205ccaca9afb8505e2d8b79593ee2edab1f67bdec27a4f14871f"
BLOCK = 24885768
TX_INDEX = 3
IMPLEMENTATION = "0xf3a3648bb1da9d3aea107da77e6f5ba9cf313127"

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default="eval/results/m6_xloot_runtime_override_probe.json")
    args = ap.parse_args()
    # Elevated/network runners may start with a different cwd; bind config to
    # this repository explicitly and never print the endpoint.
    load_dotenv(paths=(Path(__file__).resolve().parents[1] / ".env",))
    rpc = resolve_trace_rpc("mainnet")
    if not rpc:
        raise SystemExit("missing trace RPC")
    c = RpcClient(rpc, timeout=60, attempts=1)
    preflight = json.loads(Path("eval/results/m6_xloot_accounting_repair_runtime_preflight.json").read_text())
    identity = json.loads(Path("eval/results/m6_xloot_source_identity_check.json").read_text())
    if preflight.get("status") != "COMPILED" or identity.get("status") != "PASS":
        raise SystemExit("fail-closed: patched runtime is not source-identity validated")
    tx = c.eth_get_transaction(TX)
    receipt = c.eth_get_receipt(TX)
    if not tx or not receipt:
        raise SystemExit("historical transaction or receipt unavailable")
    code = "0x" + Path("eval/results/m6_xloot_accounting_repair_runtime.hex").read_text().strip().removeprefix("0x")
    override = {IMPLEMENTATION: {"code": code}}
    historical_code = c.eth_get_code(IMPLEMENTATION, hex(BLOCK - 1))
    original_override = {IMPLEMENTATION: {"code": historical_code}}
    baseline = trace_call(c, tx, BLOCK, tx_index=TX_INDEX)
    sham = trace_call(c, tx, BLOCK, original_override, "nested", TX_INDEX)
    counter = trace_call(c, tx, BLOCK, override, "nested", TX_INDEX)
    raw_baseline = None
    try:
        raw_baseline = c.call("debug_traceCall", [
            _call_object(tx), hex(BLOCK),
            {"tracer": "callTracer", "timeout": "30s", "txIndex": hex(TX_INDEX)},
        ])
    except Exception as exc:
        raw_baseline = {"raw_error": str(exc)[:512]}
    raw_counter = None
    try:
        raw_counter = c.call("debug_traceCall", [
            _call_object(tx), hex(BLOCK),
            {"tracer": "callTracer", "timeout": "30s", "txIndex": hex(TX_INDEX),
             "stateOverrides": override},
        ])
    except Exception as exc:
        raw_counter = {"raw_error": str(exc)[:512]}
    def first_error(node):
        if isinstance(node, dict):
            if node.get("error") or node.get("revertReason"):
                return {k: node.get(k) for k in ("error", "revertReason", "from", "to", "input") if node.get(k) is not None}
            for child in node.get("calls", []) or []:
                found = first_error(child)
                if found:
                    return found
        return None
    result = {
        "schema_version": 1, "case_id": "defihacklabs-xlootstaking-2026-04-15",
        "tx_hash": TX, "block": BLOCK, "tx_index": TX_INDEX,
        "implementation": IMPLEMENTATION,
        "runtime_artifact": "eval/results/m6_xloot_accounting_repair_runtime.hex",
        "baseline": baseline.__dict__, "counterfactual": counter.__dict__,
        "original_runtime_sham": sham.__dict__,
        "historical_implementation_code_bytes": (len(historical_code) - 2) // 2 if historical_code.startswith("0x") else None,
        "counterfactual_trace": raw_counter,
        "baseline_trace": raw_baseline,
        "receipt": {"status": receipt.get("status"), "gasUsed": receipt.get("gasUsed")},
        "verdict": None,
        "gates": {
            "baseline_matches_receipt": baseline.status is True and baseline.gas_used == int(receipt.get("gasUsed"), 16),
            "original_runtime_sham_matches_baseline": sham.status == baseline.status and sham.gas_used == baseline.gas_used,
            "counterfactual_comparable": False,
        },
        "counterfactual_first_error": first_error(raw_counter),
        "classification": "INCONCLUSIVE_PATCHED_RUNTIME_REVERT_BEFORE_HARM_OBSERVATION",
        "note": "Remote trace probe only; no causal promotion without full B2 acceptance, sham, and protected-harm comparison."
    }
    Path(args.output).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

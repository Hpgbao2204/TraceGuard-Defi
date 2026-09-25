"""Acquire calibration-independent Liquify stateDiff artifacts for M4."""
import json, os, sys, time
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).parents[2]
manifest = json.loads((ROOT / "docs/m4_frozen_case_manifest.json").read_text())
url = os.environ["LIQUIFY"]
out = ROOT / "eval/results/m4/raw/liquify-nethermind"
out.mkdir(parents=True, exist_ok=True)

def rpc(method, params):
    body = json.dumps({"jsonrpc":"2.0","id":1,"method":method,"params":params}).encode()
    req = Request(url, data=body, headers={"content-type":"application/json"})
    with urlopen(req, timeout=120) as r:
        return json.load(r)

identity = rpc("web3_clientVersion", [])
chain = rpc("eth_chainId", [])
if chain.get("result") != "0x1" or not str(identity.get("result", "")).lower().startswith("nethermind/"):
    raise SystemExit(f"unexpected producer: {identity} / {chain}")
for case in manifest["cases"]:
    receipt = rpc("eth_getTransactionReceipt", [case["tx_hash"]])
    prestate = rpc("debug_traceTransaction", [case["tx_hash"], {"tracer": "prestateTracer"}])
    result = rpc("trace_replayTransaction", [case["tx_hash"], ["stateDiff"]])
    artifact = {"schema_version": 1, "frozen_set_sha256": manifest["case_set_sha256"],
                "case_id": case["case_id"], "tx_hash": case["tx_hash"],
                "block": case["block"], "block_hash": case["block_hash"],
                "tx_index": case["tx_index"],
                "producer": {"engine":"nethermind", "version":identity["result"], "chain_id":1},
                "raw_sources": {"receipt_method":"eth_getTransactionReceipt",
                                "trace_method":"trace_replayTransaction", "state_method":"stateDiff"},
                "receipt": receipt, "prestate": prestate,
                "response": result}
    (out / f"{case['case_id']}.json").write_text(json.dumps(artifact, sort_keys=True, indent=2) + "\n")
    print(case["case_id"], "OK" if "result" in result and result.get("result", {}).get("stateDiff") is not None else result)
    time.sleep(0.2)

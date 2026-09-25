"""One real E5/E4 backend pilot using the canonical fresh B2 context."""
from __future__ import annotations
import json
from pathlib import Path
from core.env import load_dotenv, resolve_rpc_candidates
from core.rpc import RpcClient
from core.mutate import FlashLoanDisable
from eval.e4.execution import run_necessity
from eval.e4.models import Case

ROOT = Path(__file__).resolve().parents[2]
CASE_ID = "defihacklabs-sizeflashloanlooping-2025-08-15"
TX = "0x63aaa5a9fc87ce419c8b1711effee34e2c726b3ee2c2d28f64b963408d6ea8d3"
PROVIDER = "0x87870bca3f3fd6335c3f4ce8392d69350b4fa4e2"
SELECTOR = "0xab9c4b5d"

def main() -> None:
    load_dotenv()
    urls = resolve_rpc_candidates("mainnet")
    archive = RpcClient(urls[0], timeout=60, attempts=2, fallback_urls=urls[1:])
    tx = archive.eth_get_transaction(TX)
    receipt = archive.eth_get_receipt(TX)
    if not tx or not receipt:
        raise RuntimeError("archive transaction/receipt unavailable")
    context = ROOT / "eval/results/m4/b2-contexts-fresh" / CASE_ID
    case = Case(CASE_ID, "Size", "flash-loan", TX,
                block=int(tx["blockNumber"], 16),
                tx_index=int(tx["transactionIndex"], 16),
                mainnet_gas=int(receipt["gasUsed"], 16),
                extra={"harm_spec": {"oracle": "attacker_value_delta", "attacker": tx["from"]}})
    mutation = FlashLoanDisable(PROVIDER, selector=SELECTOR)
    rows = run_necessity(case, [mutation], archive=archive, b2_context=context,
                         run_id="e5-sizeflashloaning-backend-pilot-20260918", timeout=900)
    out = {"schema_version": 1, "artifact": "e5-sizeflashloaning-backend-pilot",
           "case_id": CASE_ID, "context": str(context), "mutation": {
               "provider": PROVIDER, "selector": SELECTOR, "operator": "FlashLoanDisable"},
           "rows": rows, "interpretation": "E4 backend pilot; not an E5 causal verdict"}
    path = ROOT / "eval/results/e5_rcfh/sizeflashloaning_backend_pilot.json"
    path.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(path), "rows": len(rows), "summary": [{k: r.get(k) for k in ("mutation", "outcome", "harm_S", "harm_Sm", "verdict", "fidelity_pass", "override_applied")} for r in rows]}, indent=2))

if __name__ == "__main__":
    main()

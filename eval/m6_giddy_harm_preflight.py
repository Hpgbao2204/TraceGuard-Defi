"""Extract a conservative protected-entity/asset-flow preflight from cached trace."""
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TX = "0x5edb66a4c2ea55bba95d36d27713e3bb1c67c3c4199a8a1759e754c6f25482e5"
PROXIES = {
    "0x9c247ccd24c23eddba399701cda24051ebf605b7": "tBTC",
    "0x51b9e3e9871247ed7c2f07539b99cb97ae99d080": "cbBTC",
    "0x1d85e7bceac3605d469debe006b46e9062238e67": "WBTC",
}
ERC20 = {"0x23b872dd": "transferFrom", "0xa9059cbb": "transfer", "0x095ea7b3": "approve"}

def main():
    row = next(json.loads(x) for x in (ROOT / "eval/results/e1_trace_cache.jsonl").read_text().splitlines()
               if json.loads(x).get("tx_hash", "").lower() == TX)
    calls = []
    def walk(n, depth=0):
        to = (n.get("to") or "").lower()
        inp = n.get("input") or ""
        selector = inp[:10].lower() if len(inp) >= 10 else inp.lower()
        if to in PROXIES or selector in ERC20 or n.get("value") not in (None, "0x0", 0, "0"):
            item = {"depth": depth, "type": n.get("type"), "from": n.get("from"),
                          "to": n.get("to"), "value": n.get("value"), "selector": selector,
                          "input": inp,
                          "operation": ERC20.get(selector, "proxy_or_native_value") if selector in ERC20 else "proxy_or_native_value"}
            if selector == "0x23b872dd" and len(inp) >= 202:
                words = [inp[10+i:10+i+64] for i in range(0, 192, 64)]
                item["decoded"] = {"token": to, "from_arg": "0x" + words[0][-40:], "to_arg": "0x" + words[1][-40:], "amount_raw": int(words[2], 16)}
            elif selector == "0xa9059cbb" and len(inp) >= 138:
                words = [inp[10+i:10+i+64] for i in range(0, 128, 64)]
                item["decoded"] = {"token": to, "to_arg": "0x" + words[0][-40:], "amount_raw": int(words[1], 16)}
            calls.append(item)
        for c in n.get("calls", []) or []: walk(c, depth + 1)
    walk(row["trace"]["tree"])
    summary = {"proxy_calls": Counter(x["to"].lower() for x in calls if (x["to"] or "").lower() in PROXIES),
               "erc20_ops": Counter(x["operation"] for x in calls if x["operation"] in ERC20.values()),
               "native_value_calls": [x for x in calls if x["value"] not in (None, "0x0", 0, "0")]}
    out = {"schema_version": 1, "status": "PREFLIGHT_ONLY", "tx_hash": TX,
           "block": row["block"], "source": "local e1_trace_cache.jsonl",
           "candidate_protected_entities": [{"address": a, "label": label, "role": "vault_proxy_candidate"} for a, label in PROXIES.items()],
           "asset_flow_calls": calls,
           "summary": {"proxy_call_counts": dict(summary["proxy_calls"]), "erc20_operation_counts": dict(summary["erc20_ops"]),
                       "native_value_call_count": len(summary["native_value_calls"])},
           "missing_for_harm_verdict": ["decoded token addresses/amounts for every transfer", "before/after protected balances or complete Transfer ledger", "asset decimals", "frozen historical valuation"],
           "causal_authorized": False}
    p = ROOT / "eval/results/m6_giddy_harm_preflight.json"
    p.write_text(json.dumps(out, indent=2) + "\n")
    print(f"wrote {p} calls={len(calls)} proxies={dict(summary['proxy_calls'])} erc20={dict(summary['erc20_ops'])}")

if __name__ == "__main__": main()

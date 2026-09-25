"""Reconcile CALL value legs from the exploratory xSNXa trace summary."""
from __future__ import annotations
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "eval/exploratory/xtoken_xsnxa_rpc_probe.json"
OUT = ROOT / "eval/exploratory/xtoken_xsnxa_value_reconciliation.json"
POOL = "0x7cd5e2d0056a7a7f09cbb86e540ef4f6dccc97dd"
TOKEN = "0x2367012ab9c3da91290f71590d5ce217721eefe4"
ENTRY = "0xc5ac25cfc2b8284e84ca47dad21cf1319f732c11"

def main() -> int:
    source = json.loads(SRC.read_text())
    incoming = defaultdict(int); outgoing = defaultdict(int); legs = []
    for frame in source["nontrivial_value_frames"]:
        if frame["type"] != "CALL":
            continue
        value = int(frame["value"], 16)
        if not value:
            continue
        incoming[frame["to"]] += value; outgoing[frame["from"]] += value
        legs.append({"from": frame["from"], "to": frame["to"], "value_raw": str(value)})
    pool_out = outgoing[POOL]
    token_in = incoming[TOKEN]
    token_out = outgoing[TOKEN]
    residual = token_in - token_out
    result = {
        "status": "RECONCILED_CANDIDATE",
        "classification": "NOT_PREREGISTERED — exploratory only",
        "counted_in_fixed_20": False,
        "method": "sum value-bearing CALL frames; exclude DELEGATECALL to avoid duplicate value accounting",
        "pool": {"address": POOL, "out_raw": str(pool_out)},
        "xsnxa_token": {"address": TOKEN, "in_raw": str(token_in), "out_raw": str(token_out), "retained_raw": str(residual)},
        "entrypoint": {"address": ENTRY, "in_raw": str(incoming[ENTRY]), "out_raw": str(outgoing[ENTRY]), "net_raw": str(incoming[ENTRY]-outgoing[ENTRY])},
        "closure": {
            "pool_out_equals_token_in": pool_out == token_in,
            "pool_out_equals_token_out_plus_token_retained": pool_out == token_out + residual,
            "unexplained_pool_value_raw": str(pool_out - token_out - residual),
            "gas_excluded": True,
        },
        "legs": legs,
        "limitations": ["CALL-value closure is not protected-entity adjudication", "token retained value is not automatically harm", "ERC20 and gas effects are not included"],
    }
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(OUT), "pool_out_raw": str(pool_out), "token_out_raw": str(token_out), "token_retained_raw": str(residual), "unexplained_pool_value_raw": result["closure"]["unexplained_pool_value_raw"], "legs": len(legs)}, indent=2))
    return 0
if __name__ == "__main__": raise SystemExit(main())

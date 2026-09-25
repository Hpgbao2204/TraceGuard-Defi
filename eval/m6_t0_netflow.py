"""T0 deterministic net-flow harm oracle for frozen ERC-20 ledgers."""
from __future__ import annotations
import json
from pathlib import Path
from eval.m6_harm_detection_v2 import HARD, REGISTRY

ZERO = "0x" + "0" * 40

def touched_addresses(flows):
    out = set()
    for f in flows:
        out.add(f["from"].lower()); out.add(f["to"].lower())
    return out - {ZERO}

def t0_detect(flows, sender, created_contracts=(), exclusions=(ZERO,)):
    if not isinstance(flows, list) or not sender:
        return {"status": "UNKNOWN", "reason": "missing ledger or sender"}
    attacker = {sender.lower(), *(x.lower() for x in created_contracts)} - set(exclusions)
    universe = touched_addresses(flows)
    protected = universe - attacker - set(exclusions)
    deltas = {a: {} for a in protected}
    for f in flows:
        token = f["token"].lower()
        if token != "eth" and token not in HARD:
            continue
        amount = int(f["amount_raw"])
        for addr, sign in ((f["to"].lower(), 1), (f["from"].lower(), -1)):
            if addr in protected:
                deltas[addr][token] = deltas[addr].get(token, 0) + sign * amount
    aggregate = {}
    for values in deltas.values():
        for token, value in values.items():
            aggregate[token] = aggregate.get(token, 0) + value
    if not aggregate:
        return {"status": "UNKNOWN", "tier": "T0", "boundary_id": "auto-complement-v1",
                "reason": "no hard-asset flow", "attacker_set": sorted(attacker),
                "protected_set": sorted(protected)}
    status = "HARM" if any(v < 0 for v in aggregate.values()) else "NO_HARM"
    return {"status": status, "tier": "T0", "boundary_id": "auto-complement-v1",
            "hard_asset_registry": REGISTRY["version"],
            "attacker_set": sorted(attacker), "protected_set": sorted(protected),
            "hard_deltas": {k: str(v) for k, v in sorted(aggregate.items())}}

def main():
    src = json.loads((Path(__file__).resolve().parents[1] / "eval/results/m6_flashloan_harm_flow_batch.json").read_text())
    rows = []
    for c in src["cases"]:
        result = t0_detect(c.get("flows", []), c.get("sender"), c.get("created_contracts", []))
        rows.append({"case": c.get("case"), **result,
                     "raw_flow_available": c.get("status") == "FLOW_EXTRACTED"})
    out = Path(__file__).resolve().parents[1] / "eval/results/m6_t0_netflow_baseline.json"
    out.write_text(json.dumps({"schema_version": 1, "scope": "T0 baseline preflight",
                               "hard_asset_registry": REGISTRY["version"],
                               "cases": rows}, indent=2) + "\n")
    from collections import Counter
    print(json.dumps({"cases": len(rows), "status_counts": dict(Counter(r["status"] for r in rows))}, indent=2))

if __name__ == "__main__": main()

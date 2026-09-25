#!/usr/bin/env python3
"""Separate VETH settlement entry/preparation from the actual reverse swap."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASE = ROOT / "eval/results/m4/b2-contexts-fresh/defihacklabs-veth-2024-11-14"
OUT = ROOT / "eval/results/e5_rcfh/veth_buyquote_dose_probe/reverse_settlement_boundary_audit.json"

def row(trace, index):
    event = trace[index]
    return {k: event.get(k) for k in ("index", "event", "depth", "type", "from", "to", "input", "value", "reverted")}

def main():
    raw = CASE / "b2-replay-m4.json"
    trace = json.loads(raw.read_text())["per_tx"][57]["call_trace"]
    out = {
        "status": "REVERSE_BOUNDARY_DISTINGUISHED",
        "case_id": "defihacklabs-veth-2024-11-14",
        "historical_sequence": [
            {"index": 77, "role": "settlement_entry", "selector": "0xe784a059", "meaning": "outer reverse-settlement call"},
            {"index": 78, "role": "settlement_preparation", "selector": "0x23b872dd", "meaning": "LamboToken transferFrom into Factory"},
            {"index": 82, "role": "settlement_preparation", "selector": "0x0902f1ac", "meaning": "pair.getReserves read"},
            {"index": 84, "role": "settlement_preparation", "selector": "0xa9059cbb", "meaning": "LamboToken transfer into pair"},
            {"index": 88, "role": "reverse_swap_entry", "selector": "0x022c0d9f", "meaning": "first actual reverse AMM swap call"},
            {"index": 98, "role": "settlement_postprocessing", "selector": "0x5c7b79f5", "meaning": "cashOut"},
        ],
        "evidence_rows": [row(trace, i) for i in (77, 78, 82, 84, 88, 98)],
        "boundary_decision": {
            "trace_77": "The settlement boundary, but too early for a narrow price-impact intervention: it includes transferFrom, getReserves, and token transfer preparation.",
            "trace_88": "The first actual pair.swap entry and the narrowest trigger for testing reverse price impact after virtual-liquidity injection.",
            "selected_trigger_for_storage_patch": 88,
            "reason": "Patch at 88 avoids changing settlement preparation and isolates the pair.swap read/invariant path. A trace-77 patch would test the broader hypothesis that the whole settlement path observes pre-mint state.",
        },
        "authorization_status": "BOUNDARY_ONLY_NO_REPLAY_AUTHORIZED",
        "limitation": "This artifact identifies the trigger; it does not implement or authorize StoragePatchAtCallSite. Same-kind sham is still required before a real patch.",
        "source_sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2) + "\n")
    print(OUT)
    print(hashlib.sha256(OUT.read_bytes()).hexdigest())

if __name__ == "__main__":
    main()

"""Materialize objective relation candidates without assigning protocol labels.

Shared trace addresses are only a review lead.  They are deliberately not
converted to ``same_protocol`` or ``same_contract_family`` automatically.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUEUE = ROOT / "eval" / "results" / "hard_negative_review_queue.csv"
CACHE = ROOT / "eval" / "results" / "e1_trace_cache.jsonl"
OUT = ROOT / "eval" / "results" / "hard_negative_relation_candidates.json"


def trace_addresses(row: dict) -> set[str]:
    trace = row.get("trace") or {}
    addresses: set[str] = set()
    for key in ("from", "to"):
        if trace.get(key):
            addresses.add(str(trace[key]).lower())
    for call in trace.get("flat_calls") or []:
        for key in ("from", "to"):
            if call.get(key):
                addresses.add(str(call[key]).lower())
    return addresses


def build() -> dict:
    cache = {}
    for line in CACHE.read_text(encoding="utf-8").splitlines():
        item = json.loads(line)
        cache[item["tx_hash"].lower()] = item
    candidates = []
    with QUEUE.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            incident = cache[row["attack_tx_hash"].lower()]
            candidate = cache[row["candidate_tx_hash"].lower()]
            overlap = sorted(trace_addresses(incident) & trace_addresses(candidate))
            if not overlap:
                continue
            candidates.append({
                "incident_case_id": row["attack_case_id"],
                "incident_tx_hash": row["attack_tx_hash"],
                "incident_block": int(row["attack_block"]),
                "candidate_tx_hash": row["candidate_tx_hash"],
                "candidate_block": int(row["candidate_block"]),
                "block_distance": int(row["block_distance"]),
                "within_window": row["within_window"].lower() == "true",
                "relation_type": "shared_trace_address",
                "shared_addresses": overlap,
                "protocol_relation": "unresolved",
                "review_required": True,
            })
    return {
        "schema_version": 1,
        "source_queue": str(QUEUE.relative_to(ROOT)),
        "source_cache": str(CACHE.relative_to(ROOT)),
        "candidate_count": len(candidates),
        "within_window_count": sum(item["within_window"] for item in candidates),
        "relation_policy": "Shared observed trace addresses identify review candidates only; they do not establish same protocol or benign intent.",
        "candidates": candidates,
    }


if __name__ == "__main__":
    payload = build()
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8", newline="\n")
    print(json.dumps({key: payload[key] for key in
                      ("candidate_count", "within_window_count")}, indent=2))

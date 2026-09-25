"""Filter anchor evidence into review leads; never assigns protocol labels."""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "eval/results/hard_negative_anchor_evidence_v2.json"
QUEUE = ROOT / "eval/results/hard_negative_review_queue.csv"
OUT = ROOT / "eval/results/hard_negative_queue_v2_leads.json"
INFRA = {
    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
    "0xdac17f958d2ee523a2206206994597c13d831ec7",
    "0x4200000000000000000000000000000000000006",
}

def main() -> None:
    data = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    metadata = data["address_metadata"]
    rows = []
    import csv
    with QUEUE.open(encoding="utf-8", newline="") as handle:
        for item in csv.DictReader(handle):
            if not item["within_window"].lower() == "true":
                continue
            incident = metadata.get(item["attack_tx_hash"].lower(), {})
            candidate = metadata.get(item["candidate_tx_hash"].lower(), {})
            ih = {x.get("bytecode_sha256") for x in incident.get("addresses", [])
                  if x.get("code_present") and x.get("bytecode_sha256")
                  and x.get("address") not in INFRA}
            ch = {x.get("bytecode_sha256") for x in candidate.get("addresses", [])
                  if x.get("code_present") and x.get("bytecode_sha256")
                  and x.get("address") not in INFRA}
            shared = sorted(ih & ch)
            if not shared:
                continue
            ia = {x["address"] for x in incident.get("addresses", [])
                  if x.get("code_present") and x.get("address") not in INFRA}
            ca = {x["address"] for x in candidate.get("addresses", [])
                  if x.get("code_present") and x.get("address") not in INFRA}
            shared_addresses = sorted(ia & ca)
            def anchors(value):
                return [{"address": x["address"], "bytecode_sha256": x["bytecode_sha256"],
                         "proxy": x.get("proxy", {})}
                        for x in value.get("addresses", [])
                        if x.get("code_present") and x.get("bytecode_sha256") in shared
                        and x.get("address") not in INFRA]
            rows.append({
                "incident_case_id": item["attack_case_id"],
                "incident_tx_hash": item["attack_tx_hash"],
                "incident_block": int(item["attack_block"]),
                "candidate_tx_hash": item["candidate_tx_hash"],
                "candidate_block": int(item["candidate_block"]),
                "block_distance": int(item["block_distance"]),
                "within_window": True,
                "relation_evidence": "shared_runtime_bytecode",
                "shared_non_infrastructure_addresses": shared_addresses,
                "relation_strength": ("strong_exact_anchor_overlap"
                                       if shared_addresses else "bytecode_lead_only"),
                "incident_anchors": anchors(incident),
                "candidate_anchors": anchors(candidate),
                "protocol_relation": "unresolved",
                "review_required": True,
            })
    out = {"schema_version": 1,
           "policy": "relation leads only; no same_protocol or benign labels inferred",
           "source_evidence": str(EVIDENCE.relative_to(ROOT)),
           "selection": "within preregistered window plus shared non-empty runtime code hash",
           "candidate_count": len(rows), "candidates": rows}
    OUT.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"candidate_count": len(rows), "status": "review_required"}, indent=2))

if __name__ == "__main__":
    main()

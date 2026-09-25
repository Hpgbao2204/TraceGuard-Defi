"""Harvest fixed-20 Harm-v2 boundary/observation availability, read-only."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs/m4_frozen_case_manifest.json"
B2 = ROOT / "eval/results/m6_b2_preflight.json"
SIDE = ROOT / "corpus/annotations/adjudication/e4_adjudication_completed_reviewer_c.jsonl"
OUT = ROOT / "eval/results/m6_harm_detection_v2_fixed20_materialized.json"

def read(path): return json.loads(path.read_text())

def main():
    manifest = read(MANIFEST)["cases"]
    assert len(manifest) == 20, "frozen manifest must contain exactly 20 cases"
    b2 = {x["case_id"]: x for x in read(B2)["cases"]}
    assert set(b2) == {x["case_id"] for x in manifest}, "B2 IDs differ from frozen manifest"
    reviews = {}
    for line in SIDE.read_text().splitlines():
        if line.strip():
            x = json.loads(line); reviews[x["case_id"]] = x
    rows = []
    for case in manifest:
        cid = case["case_id"]; review = reviews.get(cid, {}); hs = review.get("harm_spec") or {}
        victims = hs.get("victims") or review.get("protected_entities") or []
        addresses = []
        for victim in victims:
            address = victim.get("address") if isinstance(victim, dict) else victim
            if isinstance(address, str) and len(address) == 42 and address.startswith("0x"):
                addresses.append(address.lower())
        context = Path(b2[cid]["context"])
        available = {}
        for filename in ("prestates.json", "poststates.json", "receipts.json"):
            p = context / filename
            text = p.read_text(errors="ignore").lower() if p.exists() else ""
            available[filename] = {a: (a in text) for a in addresses}
        rows.append({"case_id": cid, "tx_hash": case["tx_hash"],
                     "b2_acceptance": b2[cid].get("acceptance_gate") is True,
                     "boundary_status": "EXPLICIT_ADDRESS_CANDIDATE" if addresses else "BOUNDARY_REQUIRES_ADJUDICATION",
                     "victim_addresses": addresses, "observation_files": available,
                     "native_delta_status": "PENDING_FINAL_BALANCE_EXTRACTION" if addresses else "UNKNOWN",
                     "harm_status": "PENDING_T1_ADJUDICATION"})
    OUT.write_text(json.dumps({"schema_version": 1, "scope": "fixed-20 Harm-v2 read-only materialization",
                               "source_manifest": str(MANIFEST.relative_to(ROOT)), "case_count": 20,
                               "b2_acceptance_count": sum(x["b2_acceptance"] for x in rows),
                               "causal_replay_executed": False, "cases": rows}, indent=2) + "\n")
    print(json.dumps({"cases": 20, "b2_acceptance": sum(x["b2_acceptance"] for x in rows),
                      "explicit_address_candidates": sum(x["boundary_status"] == "EXPLICIT_ADDRESS_CANDIDATE" for x in rows)}, indent=2))

if __name__ == "__main__": main()

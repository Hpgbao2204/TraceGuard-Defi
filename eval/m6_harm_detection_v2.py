"""Harm-v2 raw hard-asset detection, separated from USD quantification."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = json.loads((ROOT / "eval/e4/hard_assets_v1.json").read_text())
HARD = {a["address"] for a in REGISTRY["assets"] if a["address"]}
DETECTION_SPEC_ID = "harm-spec-v2|T0|hard-assets-v1"

def net_for_entity(flows, entity):
    entity = entity.lower()
    out = {}
    for f in flows:
        token = f["token"].lower()
        if token not in HARD:
            continue
        amount = int(f["amount_raw"])
        if f["to"].lower() == entity:
            out[token] = out.get(token, 0) + amount
        if f["from"].lower() == entity:
            out[token] = out.get(token, 0) - amount
    return out

def detect(flows, protected_entity, evidence_complete=True, tier="T1", boundary_id="explicit-entity-v1"):
    if not isinstance(flows, list) or not protected_entity:
        return {"status": "UNKNOWN", "reason": "missing hard-asset ledger or protected boundary", "detection_spec_id": DETECTION_SPEC_ID}
    deltas = net_for_entity(flows, protected_entity)
    if not deltas:
        if evidence_complete:
            return {"status": "NO_HARM", "tier": tier, "boundary_id": boundary_id, "detection_spec_id": DETECTION_SPEC_ID, "hard_asset_registry": REGISTRY["version"], "hard_deltas": {}}
        return {"status": "UNKNOWN", "reason": "raw hard-asset observation incomplete", "hard_deltas": {}, "detection_spec_id": DETECTION_SPEC_ID}
    status = "HARM" if any(v < 0 for v in deltas.values()) else "NO_HARM"
    return {"status": status, "tier": tier, "boundary_id": boundary_id, "detection_spec_id": DETECTION_SPEC_ID,
            "hard_asset_registry": REGISTRY["version"],
            "hard_deltas": {k: str(v) for k, v in deltas.items()}}

def main():
    src = json.loads((ROOT / "eval/results/m6_flashloan_harm_flow_batch.json").read_text())
    rows = []
    for case in src.get("cases", []):
        rows.append({"case": case.get("case"), "status": "UNKNOWN",
                     "reason": "protected entity adjudication required",
                     "hard_asset_registry": REGISTRY["version"],
                     "raw_flow_available": case.get("status") == "FLOW_EXTRACTED"})
    out = ROOT / "eval/results/m6_harm_detection_v2_baseline.json"
    out.write_text(json.dumps({"schema_version": 2, "scope": "baseline detection preflight",
                               "valuation_required": False, "cases": rows}, indent=2) + "\n")
    print(json.dumps({"cases": len(rows), "valuation_required": False,
                      "protected_entity_adjudicated": 0}, indent=2))

if __name__ == "__main__": main()

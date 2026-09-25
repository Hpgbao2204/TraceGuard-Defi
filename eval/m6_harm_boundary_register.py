"""Materialize/validate the T1 protected-boundary register without guessing."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "eval/results/m6_flashloan_20_status_matrix.json"
OUT = ROOT / "eval/results/m6_harm_boundary_register_v1.json"

def validate_boundary(record):
    """Return (ok, reason); never infer missing policy fields."""
    if record.get("status") != "ADJUDICATED":
        return False, "boundary_not_adjudicated"
    if not record.get("protocol_id"):
        return False, "protocol_id_missing"
    if not record.get("protected_entities"):
        return False, "protected_entities_missing"
    if not record.get("hard_assets"):
        return False, "hard_assets_missing"
    return True, None

def main():
    cases = json.loads(MATRIX.read_text())["cases"]
    rows = []
    for c in cases:
        rows.append({
            "case_id": c["name"],
            "tier": "T1",
            "boundary_id": f"protocol-explicit-v1:{c['name']}",
            "protocol_id": None,
            "protected_entities": [],
            "hard_assets": [],
            "status": "PENDING_ADJUDICATION",
            "source": None,
            "reason": "no protected boundary may be inferred from transfer magnitude",
        })
    OUT.write_text(json.dumps({"schema_version": 1,
                               "scope": "supplementary 20-case T1 boundary register",
                               "cases": rows}, indent=2) + "\n")
    print(json.dumps({"cases": len(rows), "pending": len(rows)}, indent=2))

if __name__ == "__main__": main()

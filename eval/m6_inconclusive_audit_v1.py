"""Create a conservative, evidence-backed Harm-v2 admission audit."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "eval/results/m6_flashloan_20_status_matrix.json"
FLOW = ROOT / "eval/results/m6_flashloan_harm_flow_batch.json"
OUT = ROOT / "eval/results/m6_inconclusive_audit_v1.json"

def load(path):
    return json.loads(path.read_text())

def main():
    matrix = {r["name"]: r for r in load(MATRIX)["cases"]}
    flow = {r.get("case"): r for r in load(FLOW)["cases"]}
    rows = []
    for name, r in matrix.items():
        f = flow.get(name, {})
        b2 = r.get("b2")
        flow_status = f.get("status")
        if b2 != "PASS":
            bucket, reason = 1, "BASELINE_CONTEXT_OR_FIDELITY_NOT_ACCEPTED"
        elif flow_status != "FLOW_EXTRACTED":
            bucket, reason = 5, "5A_RAW_HARD_ASSET_OBSERVATION_MISSING"
        else:
            bucket, reason = 4, "PROTECTED_BOUNDARY_NOT_ADJUDICATED"
        rows.append({
            "case_id": name,
            "baseline_fidelity": "PASS" if b2 == "PASS" else "FAIL_OR_UNVERIFIED",
            "intervention_seam": "UNKNOWN",
            "counterfactual_execution": "NOT_RUN",
            "protected_boundary": "KNOWN" if bucket == 4 else "UNKNOWN",
            "hard_asset_observation": "AVAILABLE" if flow_status == "FLOW_EXTRACTED" else "MISSING",
            "valuation": "NOT_REQUIRED_FOR_DETECTION",
            "atomicity": "UNKNOWN",
            "primary_bucket": bucket,
            "primary_reason": reason,
            "evidence": {
                "b2_status": b2,
                "flow_status": flow_status or "UNRECORDED",
                "e4_status": r.get("e4_plan", "NOT_PLANNED"),
            },
        })
    out = {
        "schema_version": 1,
        "scope": "supplementary 20-case Harm-v2 pre-intervention audit",
        "precedence": [1, 6, 2, 3, 4, 5],
        "bucket_5_subtypes": {"5A": "raw quantity unavailable", "5B": "raw quantity available, USD unavailable"},
        "causal_replay_executed": False,
        "cases": rows,
    }
    OUT.write_text(json.dumps(out, indent=2) + "\n")
    counts = {}
    for row in rows:
        counts[str(row["primary_bucket"])] = counts.get(str(row["primary_bucket"]), 0) + 1
    print(json.dumps({"total": len(rows), "bucket_counts": counts}, indent=2))

if __name__ == "__main__":
    main()

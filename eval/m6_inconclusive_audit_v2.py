"""Evidence-backed E4 causal-v3 admission audit.

This is a new namespace/report and never rewrites the historical v1 audit.
Unknown seam/atomicity/revert facts remain UNRESOLVED rather than being
invented from absence of an artifact.
"""
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "eval/results/m6_flashloan_20_status_matrix.json"
FLOW = ROOT / "eval/results/m6_flashloan_harm_flow_batch.json"
T0 = ROOT / "eval/results/m6_harm_v2_t0_baseline.json"
OUT = ROOT / "eval/results/e4_causal_v3_inconclusive_audit.json"

def main():
    matrix = {x["name"]: x for x in json.loads(MATRIX.read_text())["cases"]}
    flow = {x["case"]: x for x in json.loads(FLOW.read_text())["cases"]}
    t0 = {x["case_id"]: x for x in json.loads(T0.read_text())["cases"]}
    rows = []
    for name, m in matrix.items():
        f, raw = flow.get(name, {}), t0.get(name, {})
        b2 = m.get("b2")
        flow_status = f.get("status")
        protected = f.get("protected_entity")
        mutation_count = int(m.get("mutation_count") or 0)
        # Precedence is frozen: fidelity, explicit seam, observed CF break,
        # boundary, then observation.  Missing evidence is never guessed.
        bucket = None
        reason = "UNRESOLVED_NO_ADJUDICATED_PRIMARY_BLOCKER"
        classification = "UNRESOLVED"
        if b2 != "PASS":
            bucket, reason, classification = 1, "BASELINE_FIDELITY_OR_CONTEXT_NOT_ACCEPTED", "B1"
        elif mutation_count == 0:
            bucket, reason, classification = 2, "NO_RECORDED_INTERVENTION_SEAM", "B2"
        elif protected in (None, "", "PENDING_ADJUDICATION"):
            bucket, reason, classification = 4, "PROTECTED_BOUNDARY_NOT_FROZEN", "B4"
        elif flow_status != "FLOW_EXTRACTED":
            bucket, reason, classification = 5, "RAW_HARM_OBSERVATION_UNAVAILABLE_5A", "B5"
        elif raw.get("observation", {}).get("status") == "UNKNOWN":
            bucket, reason, classification = 5, "RAW_HARM_OBSERVATION_UNKNOWN_5A", "B5"
        else:
            bucket, reason, classification = 5, "RAW_HARM_AVAILABLE_USD_OPTIONAL_5B", "B5"
        rows.append({
            "case_id": name,
            "classification": classification,
            "primary_bucket": bucket,
            "primary_reason": reason,
            "baseline_fidelity": b2,
            "intervention_seam_evidence": "RECORDED" if mutation_count else "NOT_RECORDED",
            "mutation_count": mutation_count,
            "counterfactual_execution": "NOT_RUN",
            "protected_boundary": "FROZEN" if protected not in (None, "", "PENDING_ADJUDICATION") else "UNKNOWN",
            "raw_harm_observation": flow_status or "UNRECORDED",
            "atomicity": "UNRESOLVED",
            "evidence": {"b2": b2, "e4_plan": m.get("e4_plan"), "flow_status": flow_status, "t0_status": raw.get("observation", {}).get("status")},
        })
    counts = Counter(r["classification"] for r in rows)
    out = {
        "schema_version": 2,
        "protocol": "E4-CAUSAL-V3",
        "scope": "frozen-20 pre-intervention audit; historical v1 preserved",
        "causal_replay_executed": False,
        "precedence": ["B1", "B6", "B2", "B3", "B4", "B5"],
        "bucket_3_subtypes": ["STRUCTURAL_PRECONDITION_BREAK", "MECHANISM_BLOCKING_REVERT", "CAPITAL_SOURCE_BREAK", "UNKNOWN_REVERT"],
        "unresolved_policy": "do_not_infer_missing_seam_revert_or_atomicity_evidence",
        "cases": rows,
        "counts": dict(counts),
    }
    OUT.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"total": len(rows), "counts": dict(counts)}, indent=2))

if __name__ == "__main__": main()

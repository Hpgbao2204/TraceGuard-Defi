"""Run a bounded seam pilot through the E5 adapter, without replay backend."""
from __future__ import annotations
import json
from pathlib import Path
from .replay_adapter import run_tier1

ROOT = Path(__file__).resolve().parents[2]
CASES = [
    "defihacklabs-veth-2024-11-14",
    "defihacklabs-muredistribution-2026-05-21",
]

def main() -> None:
    out = []
    mapping = {x["case_id"]: x for x in json.loads((ROOT / "eval/results/e5_rcfh/claim_mapping_v1.json").read_text())["cases"]}
    for case_id in CASES:
        doc = json.loads((ROOT / "eval/results/e5_rcfh/seam_groups" / f"{case_id}.json").read_text())
        # Select only from the machine mapping's claim-compatible groups. This
        # prevents the old pilot bug that picked an incidental AMM read for a
        # flash-loan claim. It remains a pilot input, not adjudication.
        mapped = mapping[case_id]["mapped_operator_types"]
        groups = [g for g in doc["seam_groups"] if g["type"] in mapped]
        if len(groups) != 1:
            out.append({"case_id": case_id, "adapter_execution_status": "NOT_TESTABLE", "reason": "CLAIM_COMPATIBLE_SEAM_NOT_UNIQUE", "candidate_group_ids": [g["group_id"] for g in groups], "replay_authorized": False})
            continue
        selected = groups[0]
        claim = {"victim_or_asset_addresses": [], "harm_write_trace_index": None}
        result = run_tier1({}, selected, claim, replay_backend=None)
        out.append({
            "case_id": case_id,
            "group_id": selected["group_id"],
            "operator": selected["type"],
            "callee": selected["callee"],
            "adapter_execution_status": result.execution_status,
            "reason": result.reason,
            "harm_vector": result.harm_vector,
            "replay_authorized": False,
            "interpretation": "adapter wiring/preflight only; not a historical replay or causal result",
        })
    result = {"schema_version": 1, "artifact": "e5-seam-pilot", "corpus_id": "m4-frozen-20", "cases": out}
    path = ROOT / "eval/results/e5_rcfh/seam_pilot_veth_mure.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2))

if __name__ == "__main__": main()

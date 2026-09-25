"""Record dose-response readiness without fabricating historical doses."""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "eval/results/e5_rcfh/dose_response_preflight.json"

def main() -> None:
    mapping = json.loads((ROOT / "eval/results/e5_rcfh/claim_mapping_v1.json").read_text())
    eligible = []
    for item in mapping["cases"]:
        if item["status"] != "MAPPED_CANDIDATE":
            continue
        types = set(item["mapped_operator_types"])
        if types & {"oracle_read", "amm_reserve_read"}:
            eligible.append({
                "case_id": item["case_id"],
                "operator_types": sorted(types & {"oracle_read", "amm_reserve_read"}),
                "status": "NOT_RUN",
                "reason": "MISSING_REVIEWED_SEAM_AND_REPLAY_BACKEND",
                "dose_grid": None,
                "observations": [],
                "revert_is_null_harm": True,
            })
    result = {
        "schema_version": 1,
        "artifact": "e5-dose-response-preflight",
        "corpus_id": "m4-frozen-20",
        "scope": "readiness only; no historical dose replay",
        "policy": "revert is null harm; a dose is meaningful only with comparable execution and HarmVector",
        "cases": eligible,
        "status": "NOT_RUN",
        "reason": "No reviewed claim-boundary seam and no replay backend supplied",
    }
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"candidate_count": len(eligible), "status": result["status"]}, indent=2))

if __name__ == "__main__":
    main()

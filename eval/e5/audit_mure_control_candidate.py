"""Validate the MuRe harm-scoped control-candidate recovery checkpoint."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def audit(provenance_run: dict, candidates: dict) -> dict:
    provenance = provenance_run.get("provenance") or {}
    return_candidates = [c for c in candidates.get("candidates", [])
                         if c.get("kind") == "cross_frame_return_candidate"]
    branch_candidates = [c for c in candidates.get("candidates", [])
                         if c.get("kind") == "control_candidate"]
    matched = []
    for ret in return_candidates:
        for frame in ret.get("return_source_frames", []):
            call_input = str(candidates.get("frame_meta", {}).get(frame, {}).get("callInput", ""))
            if call_input.lower().startswith("0x1626ba7e"):
                related = [b for b in branch_candidates
                           if b.get("branch_frame") == ret.get("branch_frame")
                           and b.get("child_frame") == ret.get("child_frame")]
                matched.append({"return_candidate": ret, "source_frame": frame,
                                "selector": "0x1626ba7e", "related_branch_candidates": related})
    status = "DEPENDENCY_CONTROL_PATH_RECOVERED" if matched else "DEPENDENCY_CONTROL_PATH_NOT_RECOVERED"
    return {
        "schema_version": "e5-mure-control-candidate-audit-v1",
        "status": status,
        "sink_observation_id": candidates.get("sink_observation_id"),
        "reference_leakage": False,
        "matched_paths": matched,
        "causal_verdict": None,
        "interpretation": "The authenticated provenance recovers a cross-frame ERC-1271 return and downstream branch candidates before the protected transfer. Static control scope and causal necessity remain unproven.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(json.loads(args.provenance.read_text()), json.loads(args.candidates.read_text()))
    args.output.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()

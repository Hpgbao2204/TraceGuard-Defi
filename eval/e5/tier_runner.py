"""Fail-closed Tier-1/Tier-2 E5 runners.

The runner consumes the reviewed mapping and only invokes an injected replay
adapter. Without that adapter it emits machine-readable NOT_TESTABLE records;
it never treats a missing replay as a negative causal result.
"""
from __future__ import annotations
import json
from pathlib import Path
from eval.e5.replay_adapter import run_tier1 as run_candidate_tier1

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "eval/results/e5_rcfh"


def run_reviewed_candidate(case: dict, seam_group: dict, claim: dict, *, replay_backend=None):
    """Connected E5 entry point for a reviewed E4 candidate."""
    return run_candidate_tier1(case, seam_group, claim, replay_backend=replay_backend)


def run_tier1(*, mapping_path: Path = OUT / "claim_mapping_v1.json", replay_adapter=None) -> dict:
    mapping = json.loads(mapping_path.read_text())
    rows = []
    for case in mapping["cases"]:
        if case["status"] != "MAPPED_CANDIDATE":
            status, reason = "CLAIM_NOT_LOCALIZABLE", case["status"]
        elif replay_adapter is None:
            status, reason = "NOT_TESTABLE", "REPLAY_ADAPTER_NOT_SUPPLIED"
        else:
            status, reason = replay_adapter(case)
        rows.append({"case_id": case["case_id"], "status": status, "reason": reason, "same_kind_sham_pass": False})
    return {"schema_version": 1, "artifact": "e5-tier1", "corpus_id": "m4-frozen-20", "cases": rows}


def run_tier2(tier1: dict) -> dict:
    rows = [{"case_id": x["case_id"], "status": "NOT_TESTABLE", "reason": "TIER1_NOT_SUPPORTED_WITH_COMPARABLE_REPLAY", "profile": None} for x in tier1["cases"]]
    return {"schema_version": 1, "artifact": "e5-tier2", "corpus_id": "m4-frozen-20", "cases": rows}


def main() -> None:
    t1 = run_tier1()
    t2 = run_tier2(t1)
    (OUT / "tier1_runner_result.json").write_text(json.dumps(t1, indent=2) + "\n")
    (OUT / "tier2_runner_result.json").write_text(json.dumps(t2, indent=2) + "\n")
    print(json.dumps({"tier1_cases": len(t1["cases"]), "tier2_cases": len(t2["cases"]), "replay": "NOT_TESTABLE"}, indent=2))


if __name__ == "__main__": main()

import json
from pathlib import Path

from eval.e5.run_causal_candidate_pilot import run


def test_real_case_pilot_artifact_is_fail_closed_for_onyx():
    root = Path(__file__).parents[1]
    manifest = root / "eval/results/e5_rcfh/causal_candidate_pilot_manifest_v1.json"
    result = run(manifest)
    by_case = {c["case_id"]: c for c in result["cases"]}
    assert by_case["defihacklabs-onyxdao-2024-09-26"]["status"] == "NOT_OBSERVABLE"
    assert result["summary"]["case_count"] == 5


def test_real_case_pilot_preserves_veth_boundary_order():
    root = Path(__file__).parents[1]
    manifest = root / "eval/results/e5_rcfh/causal_candidate_pilot_manifest_v1.json"
    result = run(manifest)
    veth = next(c for c in result["cases"] if c["case_id"].endswith("veth-2024-11-14"))
    assert veth["veth_boundary_check"]["trace45_above_trace17"] is True
    assert veth["status"] == "REVIEW_REQUIRED"

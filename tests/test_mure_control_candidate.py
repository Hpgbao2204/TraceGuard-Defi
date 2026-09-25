import json
from eval.e5.audit_mure_control_candidate import audit


def test_mure_audit_requires_erc1271_selector_and_related_branch():
    result = audit(
        {"provenance": {"status": "PROVENANCE_COMPLETE"}},
        {"sink_observation_id": "o0", "frame_meta": {"f2": {"callInput": "0x1626ba7e00"}},
         "candidates": [
             {"kind": "cross_frame_return_candidate", "return_source_frames": ["f2"], "branch_frame": "p", "child_frame": "c"},
             {"kind": "control_candidate", "branch_frame": "p", "child_frame": "c"},
         ]},
    )
    assert result["status"] == "DEPENDENCY_CONTROL_PATH_RECOVERED"
    assert result["causal_verdict"] is None

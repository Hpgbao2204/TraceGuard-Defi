import json
from pathlib import Path


def test_mure_taint_is_supporting_only_and_path_is_broken():
    data = json.loads(Path("eval/results/e5_rcfh/mure_security_property_taint_v1.json").read_text())
    assert data["not_a_verdict"] is True
    assert data["counterfactual_observation"]["path_status"] == "BROKEN_AT_VALIDATION_BOUNDARY"
    assert data["counterfactual_observation"]["transfer_log_committed"] is False

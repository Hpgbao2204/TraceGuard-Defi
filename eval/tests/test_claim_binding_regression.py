import json
from pathlib import Path


def test_dose_prefix_cannot_be_used_as_trace45_root_evidence():
    data = json.loads(Path("eval/results/e5_rcfh/causal_slice_regression_v1.json").read_text())
    veth = data["veth"]
    assert veth["claim_binding_required"] is True
    assert veth["dose_input_intervention"]["trace_index"] != veth["root_boundary_reference"]["trace_index"]
    assert veth["root_boundary_reference"]["prefix_probe_against_dose_pair"]["valid"] is False

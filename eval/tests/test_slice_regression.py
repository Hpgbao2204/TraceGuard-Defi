import json
from pathlib import Path


def test_slice_regression_artifact_has_bounded_results():
    data = json.loads(Path("eval/results/e5_rcfh/causal_slice_regression_v1.json").read_text())
    assert data["veth"]["status"] == "PASS_FOR_DOSE_INTERVENTION_ONLY"
    assert data["veth"]["claim_binding_required"] is True
    assert data["veth"]["dose_input_intervention"]["prefix"]["valid"] is True
    assert data["veth"]["root_boundary_reference"]["prefix_probe_against_dose_pair"]["valid"] is False
    assert data["veth"]["four_cell_claim_bound_probe"]["prefix"]["valid"] is True
    assert data["veth"]["trace_45_artifact_status"] == "NOT_AVAILABLE_FOR_DIRECT_COUNTERFACTUAL_PREFIX_CHECK"
    assert data["summerfi"]["status"] == "BASELINE_EXTRACTION_ONLY"
    assert data["non_circularity_check"] == "PASS"

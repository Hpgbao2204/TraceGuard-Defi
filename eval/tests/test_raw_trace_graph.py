import json
from pathlib import Path


def test_raw_trace_graph_is_automatically_extracted():
    data = json.loads(Path("eval/results/e5_rcfh/mure_raw_trace_causal_graph_v1.json").read_text())
    assert data["validation"]["hand_authored_nodes"] is False
    assert data["validation"]["erc1271_in_slice"] is True
    assert data["validation"]["transfer_in_slice"] is True
    assert data["validation"]["outcome_in_slice"] is True

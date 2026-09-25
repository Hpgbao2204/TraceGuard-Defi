from pathlib import Path
from eval.e5.trace_candidate_extractor import extract_b2_call_nodes

ROOT = Path(__file__).parents[1]

def test_extractor_finds_veth_helper_from_raw_trace():
    p = ROOT / "eval/results/m4/b2-contexts-fresh/defihacklabs-veth-2024-11-14/b2-replay-m4.json"
    nodes = extract_b2_call_nodes(p)
    assert any(n["trace_index"] == 45 and n["selector"] == "0x6c0472da" for n in nodes)

def test_extractor_finds_mure_auth_call_without_reference_input():
    p = ROOT / "eval/results/m4/b2-contexts-fresh/defihacklabs-muredistribution-2026-05-21/b2-replay-m4.json"
    nodes = extract_b2_call_nodes(p)
    assert any(n["trace_index"] == 18 and n["selector"] == "0x1626ba7e" for n in nodes)

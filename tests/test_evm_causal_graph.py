from eval.e5.evm_causal_graph import backward_slice, build_evm_graph, rank_semantic_candidates


def test_generic_evm_graph_preserves_call_and_return_dataflow():
    graph = build_evm_graph([
        {"event": "enter", "depth": 1, "from": "A", "to": "P", "input": "0x0902f1ac"},
        {"event": "exit", "depth": 1, "from": "P", "to": "A", "output": "0x01"},
    ], telemetry=[{
        "node_id": "harm", "kind": "outcome", "semantic": "ASSET_TRANSFER",
        "source_node": "return:1", "target_node": "harm", "relation": "dataflow",
    }])
    assert graph["nodes"][0]["semantic"] == "PRICE_READ"
    assert backward_slice(graph, "harm") == ["call:0", "harm", "return:1"]


def test_semantic_ranking_is_not_authorization():
    graph = build_evm_graph([
        {"event": "enter", "depth": 1, "from": "A", "to": "P", "input": "0x1626ba7e"},
        {"event": "exit", "depth": 1, "from": "P", "to": "A", "output": "0x01"},
    ], telemetry=[{
        "node_id": "harm", "kind": "outcome", "semantic": "ASSET_TRANSFER",
        "source_node": "return:1", "target_node": "harm",
    }])
    candidates = rank_semantic_candidates(graph, "harm")
    assert candidates[0]["semantic"] == "AUTH_CHECK"
    assert candidates[0]["status"] == "REVIEW_REQUIRED"

from eval.causal_slice import backward_slice


def test_backward_slice_keeps_only_ancestors_of_sink():
    nodes = [{"id": x} for x in ("a", "b", "c", "unrelated")]
    edges = [{"src": "a", "dst": "b"}, {"src": "b", "dst": "c"}]
    assert backward_slice(nodes, edges, "c") == ["a", "b", "c"]

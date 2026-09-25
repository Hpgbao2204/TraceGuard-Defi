from eval.causal_scm import Edge, Node, Provenance, SCM, SCMError


def _model():
    p = Provenance("trace", "tx-1", 10, 0.95)
    return SCM(
        [
            Node("oracle", "mechanism", observed=100, interventionable=True, provenance=p),
            Node("quote", "state", equation=lambda v: v["oracle"] * 2, interventionable=True, provenance=p),
            Node("harm", "outcome", equation=lambda v: v["quote"] > 150, provenance=p),
            Node("unrelated", "mechanism", observed=7, provenance=p),
        ],
        [Edge("oracle", "quote", "dataflow", p), Edge("quote", "harm", "predicate", p)],
    )


def test_scm_evaluates_and_intervenes_on_descendants():
    scm = _model()
    assert scm.evaluate()["harm"] is True
    cf = scm.do("oracle", 50, "harm")
    assert cf.values["quote"] == 100
    assert cf.values["harm"] is False
    assert cf.outcome_changed is True


def test_backward_slice_excludes_unrelated_node_and_ranks_candidate():
    scm = _model()
    assert scm.backward_slice("harm") == ["oracle", "quote", "harm"]
    ranked = scm.rank_candidates("harm")
    assert [x.node_id for x in ranked] == ["quote", "oracle"]
    assert all(x.status == "REVIEW_REQUIRED" for x in ranked)


def test_cycle_is_rejected():
    p = Provenance("trace")
    try:
        SCM([Node("a", "state"), Node("b", "state")], [Edge("a", "b", "x", p), Edge("b", "a", "x", p)])
    except SCMError as exc:
        assert "cycle" in str(exc)
    else:
        raise AssertionError("cycle must be rejected")


def test_non_interventionable_node_is_rejected():
    scm = _model()
    try:
        scm.do("unrelated", 0)
    except SCMError as exc:
        assert "not interventionable" in str(exc)
    else:
        raise AssertionError("non-interventionable node must be rejected")

import pytest

from eval.e5.state_coupling import (
    StateCouplingError,
    ConsistencyPredicate,
    EvidenceEvent,
    StateEdge,
    StateNode,
    connected_components,
    consistency_report,
    coupled_intervention_set,
    nodes_from_state_diff,
    minimal_mutation_set,
    evaluate_predicates,
    recover_candidate_edges,
    state_consistency_gate,
)


def _fixture():
    return [
        StateNode("pool.reserve", "storage", "0xpool", "reserve"),
        StateNode("pool.balance", "erc20_balance", "0xpool", "0xtoken"),
        StateNode("victim.balance", "erc20_balance", "0xvictim", "0xtoken"),
        StateNode("unrelated", "storage", "0xother", "slot0"),
    ], [
        ("pool.reserve", "pool.balance"),
        ("pool.balance", "victim.balance"),
    ]


def test_groups_are_deterministic_and_keep_unrelated_state_separate():
    nodes, edges = _fixture()
    assert connected_components(nodes, edges) == [
        ("pool.balance", "pool.reserve", "victim.balance"),
        ("unrelated",),
    ]


def test_target_closure_contains_coupled_balances():
    nodes, edges = _fixture()
    assert coupled_intervention_set("pool.reserve", nodes, edges) == (
        "pool.balance",
        "pool.reserve",
        "victim.balance",
    )


def test_incomplete_single_slot_mutation_fails_closed():
    nodes, edges = _fixture()
    report = consistency_report(nodes, edges, declared_mutation=["pool.reserve"])
    assert report["complete"] is False
    assert report["missing_coupled_nodes"] == ("pool.balance", "victim.balance")


def test_complete_coupled_mutation_is_admissible_for_next_layer_only():
    nodes, edges = _fixture()
    report = consistency_report(
        nodes,
        edges,
        declared_mutation=["pool.reserve", "pool.balance", "victim.balance"],
    )
    assert report["complete"] is True


def test_unknown_edge_and_malformed_balance_fail_closed():
    with pytest.raises(StateCouplingError):
        connected_components(
            [StateNode("x", "erc20_balance", "0xpool", "0xtoken")],
            [("x", "missing")],
        )
    with pytest.raises(StateCouplingError):
        connected_components([StateNode("x", "erc20_balance")], [])


def test_b2_diff_adapter_requires_provenance_and_emits_changed_cells():
    pre = {"0xAA": {"balance": "0x01", "storage": {"0x0": "0x01", "0x1": "0x09"}}}
    post = {"0xaa": {"balance": "0x02", "storage": {"0x0": "0x02", "0x1": "0x09"}}}
    nodes = nodes_from_state_diff(pre, post, source="b2/poststates.json:tx0")
    assert [node.node_id for node in nodes] == [
        "native:0xaa",
        "storage:0xaa:0x0",
    ]
    assert all(node.provenance == "b2/poststates.json:tx0" for node in nodes)
    with pytest.raises(StateCouplingError):
        nodes_from_state_diff(pre, post, source="")


def test_typed_closure_excludes_harm_observation():
    nodes = [
        StateNode("reserve", "storage", "0xpool", "0x01"),
        StateNode("pool_balance", "erc20_balance", "0xpool", "0xtoken"),
        StateNode("victim_loss", "protected_observation", provenance="review:v1"),
    ]
    edges = [
        StateEdge("reserve", "pool_balance", "CONSISTENCY_REQUIRES", "fixture"),
        StateEdge("pool_balance", "victim_loss", "HARM_OBSERVATION", "fixture"),
    ]
    assert minimal_mutation_set("reserve", nodes, edges) == (
        "pool_balance",
        "reserve",
    )


def test_typed_closure_rejects_missing_provenance_and_unknown_relation():
    nodes = [StateNode("x", "derived_accounting", provenance="fixture")]
    with pytest.raises(StateCouplingError):
        minimal_mutation_set(
            "x", nodes,
            [StateEdge("x", "x", "CONSISTENCY_REQUIRES")],
        )
    with pytest.raises(StateCouplingError):
        minimal_mutation_set(
            "x", nodes,
            [StateEdge("x", "x", "UNKNOWN", "fixture")],
        )
    with pytest.raises(StateCouplingError):
        minimal_mutation_set(
            "x", nodes,
            [StateEdge("x", "x", "MIRRORS", "AMBIGUOUS")],
        )


def test_typed_closure_follows_direction_and_cycles_terminate():
    nodes = [
        StateNode("a", "storage", "0xa", "0x01"),
        StateNode("b", "derived_accounting", provenance="fixture"),
        StateNode("c", "storage", "0xc", "0x03"),
    ]
    edges = [
        StateEdge("a", "b", "CONSISTENCY_REQUIRES", "fixture"),
        StateEdge("b", "a", "MIRRORS", "fixture"),
        StateEdge("c", "a", "CONSISTENCY_REQUIRES", "fixture"),
    ]
    assert minimal_mutation_set("a", nodes, edges) == ("a", "b")


def test_multiple_seeds_are_deterministic_and_do_not_cross_independent_components():
    nodes, edges = _fixture()
    assert minimal_mutation_set(
        {"pool.reserve", "unrelated"}, nodes,
        [
            StateEdge("pool.reserve", "pool.balance", "CONSISTENCY_REQUIRES", "fixture"),
        ],
    ) == ("pool.balance", "pool.reserve", "unrelated")


def _predicate(kind, inputs, output=None, params=()):
    return ConsistencyPredicate(
        predicate_id=f"p-{kind.lower()}",
        kind=kind,
        inputs=tuple(inputs),
        output=output,
        params=tuple(params),
        source="fixture",
        confidence="HIGH",
        version="fixture-v1",
    )


def test_predicates_cover_equal_delta_sum_range_packed_and_derived():
    values = {
        "reserve": 10,
        "balance": 10,
        "delta_a": 4,
        "delta_b": 4,
        "part_a": 2,
        "part_b": 3,
        "total": 5,
        "packed": 0xAB00,
        "field": 0xAB,
        "derived": 10,
        "source": 10,
    }
    result = evaluate_predicates(values, [
        _predicate("EQUAL", ["reserve", "balance"]),
        _predicate("DELTA_EQUAL", ["delta_a", "delta_b"]),
        _predicate("SUM", ["part_a", "part_b"], "total"),
        _predicate("RANGE", ["reserve"], params=(0, 20)),
        _predicate("PACKED_FIELD", ["packed"], "field", (8, 8)),
        _predicate("DERIVED", ["source"], "derived"),
    ])
    assert result["status"] == "CONSISTENT"


def test_predicate_failure_and_missing_value_are_distinct():
    failed = evaluate_predicates(
        {"a": 1, "b": 2},
        [_predicate("EQUAL", ["a", "b"])],
    )
    assert failed["status"] == "INCONSISTENT"
    unknown = evaluate_predicates(
        {"a": 1},
        [_predicate("EQUAL", ["a", "missing"])],
    )
    assert unknown["status"] == "UNKNOWN"


def test_empty_predicates_fail_closed():
    assert evaluate_predicates({"a": 1}, []) ["status"] == "UNKNOWN"


def test_gate_requires_predicates_and_all_closure_values():
    nodes = [
        StateNode("a", "storage", "0xa", "0x01"),
        StateNode("b", "storage", "0xb", "0x02"),
    ]
    edges = [StateEdge("a", "b", "CONSISTENCY_REQUIRES", "fixture")]
    no_predicate = state_consistency_gate(
        {"a": 1, "b": 1}, nodes, edges, [], seeds=["a"]
    )
    assert no_predicate["status"] == "NOT_TESTABLE"
    incomplete = state_consistency_gate(
        {"a": 1}, nodes, edges, [_predicate("EQUAL", ["a", "a"])], seeds=["a"]
    )
    assert incomplete["status"] == "NOT_TESTABLE"


def test_predicate_provenance_and_shape_fail_closed():
    base = dict(kind="EQUAL", inputs=("a", "b"))
    with pytest.raises(StateCouplingError):
        evaluate_predicates({"a": 1, "b": 1}, [
            ConsistencyPredicate("p", source=None, confidence="HIGH",
                                 version="v1", **base)
        ])
    with pytest.raises(StateCouplingError):
        evaluate_predicates({"a": 1, "b": 1}, [
            ConsistencyPredicate("p", source="fixture", confidence="HIGH",
                                 version=None, **base)
        ])
    with pytest.raises(StateCouplingError):
        evaluate_predicates({"a": 1}, [
            ConsistencyPredicate("p", kind="RANGE", inputs=("a",),
                                 source="fixture", confidence="HIGH", version="v1")
        ])


def test_dynamic_evidence_only_proposes_observational_edges():
    result = recover_candidate_edges(
        [
            EvidenceEvent("r", "STATE_READ", "reserve", 1, "trace:1"),
            EvidenceEvent("c", "EXTERNAL_CALL", "swap", 2, "trace:2"),
            EvidenceEvent("h", "HARM", "victim_loss", 3, "trace:3"),
        ],
        harm_event_id="h",
    )
    assert result["status"] == "CANDIDATE_EDGES"
    assert result["mutation_authorized"] is False
    assert {edge.relation for edge in result["edges"]} == {
        "READ_DEPENDENCY", "HARM_OBSERVATION"
    }


def test_dynamic_evidence_rejects_ambiguous_ordering():
    with pytest.raises(StateCouplingError):
        recover_candidate_edges(
            [
                EvidenceEvent("r", "STATE_READ", "reserve", 1, "trace:1"),
                EvidenceEvent("h", "HARM", "victim_loss", 1, "trace:1"),
            ],
            harm_event_id="h",
        )


def test_state_consistency_gate_requires_consistent_predicates_and_never_authorizes():
    nodes = [
        StateNode("reserve", "storage", "0xpool", "0x1"),
        StateNode("balance", "erc20_balance", "0xpool", "0xtoken"),
    ]
    edges = [
        StateEdge("reserve", "balance", "CONSISTENCY_REQUIRES", "fixture"),
    ]
    result = state_consistency_gate(
        {"reserve": 10, "balance": 10},
        nodes,
        edges,
        [_predicate("EQUAL", ["reserve", "balance"])],
        seeds={"reserve"},
    )
    assert result["status"] == "READY_FOR_REPLAY_PRECHECK"
    assert result["mutation_authorized"] is False

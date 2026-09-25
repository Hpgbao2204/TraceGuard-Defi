import pytest

from eval.e5.temporal import (
    DependencyEdge,
    DependencyNode,
    TemporalModelError,
    branch_state,
    dependency_dag,
    transition_digest,
    validate_transition,
)


def test_branch_requires_proof_bound_parent_and_marks_synthetic():
    branch = branch_state(
        parent_state="root:b-1",
        child_state="synthetic:b",
        block=100,
        proof_bound=True,
        intervention_id="mutation:fixture",
        chain_id=1,
        parent_hash="0xparent",
        parent_state_root="0xroot",
        child_state_digest=transition_digest(
            parent_state="root:b-1", block=100,
            intervention_id="mutation:fixture", child_state="synthetic:b",
        ),
        transition_artifact_hash="sha256:fixture",
    )
    assert branch.counterfactual is True
    assert branch.parent_state == "root:b-1"


def test_unproofed_branch_is_not_testable():
    with pytest.raises(TemporalModelError):
        branch_state(
            parent_state="historical",
            child_state="synthetic",
            block=100,
            proof_bound=False,
            intervention_id="mutation",
        )


def test_synthetic_child_digest_binds_parent_and_intervention():
    digest = transition_digest(
        parent_state="root", block=100, intervention_id="mut", child_state="child"
    )
    transition = branch_state(
        parent_state="root", child_state="child", block=100,
        proof_bound=True, intervention_id="mut", chain_id=1,
        parent_hash="0xp", parent_state_root="0xroot",
        child_state_digest=digest, transition_artifact_hash="sha256:artifact",
    )
    validate_transition(transition)
    with pytest.raises(TemporalModelError):
        branch_state(
            parent_state="root", child_state="child", block=100,
            proof_bound=True, intervention_id="other", chain_id=1,
            parent_hash="0xp", parent_state_root="0xroot",
            child_state_digest=digest, transition_artifact_hash="sha256:artifact",
        )


def test_temporal_dag_orders_cross_block_dependency():
    nodes = [
        DependencyNode("manipulate", 100, "STATE_WRITE", "trace:100"),
        DependencyNode("read", 101, "ORACLE_READ", "trace:101"),
        DependencyNode("harm", 101, "HARM", "trace:101"),
    ]
    edges = [
        DependencyEdge("manipulate", "read", "TEMPORAL_READ", "trace:100-101"),
        DependencyEdge("read", "harm", "CAUSAL_FLOW", "trace:101"),
    ]
    assert [node.node_id for node in dependency_dag(nodes, edges)] == [
        "manipulate", "read", "harm"
    ]


def test_temporal_cycle_and_missing_provenance_fail_closed():
    nodes = [
        DependencyNode("a", 1, "READ", "x"),
        DependencyNode("b", 2, "WRITE", "y"),
    ]
    with pytest.raises(TemporalModelError):
        dependency_dag(
            nodes,
            [
                DependencyEdge("a", "b", "FLOW", "x"),
                DependencyEdge("b", "a", "FLOW", "y"),
            ],
        )
    with pytest.raises(TemporalModelError):
        dependency_dag([DependencyNode("a", 1, "READ", "")], [])


def test_temporal_edges_cannot_move_backwards_or_cross_chain():
    nodes = [
        DependencyNode("later", 102, "WRITE", "x", chain_id=1),
        DependencyNode("earlier", 101, "READ", "y", chain_id=1),
    ]
    with pytest.raises(TemporalModelError):
        dependency_dag(nodes, [DependencyEdge("later", "earlier", "FLOW", "x")])
    cross_chain = [
        DependencyNode("a", 1, "READ", "x", chain_id=1),
        DependencyNode("b", 2, "WRITE", "y", chain_id=2),
    ]
    with pytest.raises(TemporalModelError):
        dependency_dag(cross_chain, [DependencyEdge("a", "b", "FLOW", "x")])

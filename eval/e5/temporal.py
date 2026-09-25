"""Fail-closed temporal counterfactual model for E5."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Iterable


class TemporalModelError(ValueError):
    pass


@dataclass(frozen=True)
class StateTransition:
    block: int
    parent_state: str
    child_state: str
    provenance: str
    counterfactual: bool = False
    chain_id: int | None = None
    parent_hash: str | None = None
    parent_state_root: str | None = None
    child_state_digest: str | None = None
    transition_artifact_hash: str | None = None


@dataclass(frozen=True)
class DependencyNode:
    node_id: str
    block: int
    kind: str
    provenance: str
    chain_id: int | None = None
    block_hash: str | None = None
    parent_hash: str | None = None


@dataclass(frozen=True)
class DependencyEdge:
    source: str
    target: str
    relation: str
    provenance: str


def transition_digest(*, parent_state: str, block: int, intervention_id: str,
                      child_state: str) -> str:
    """Return the canonical digest binding a synthetic child to its inputs."""
    payload = json.dumps({
        "parent_state": parent_state,
        "block": block,
        "intervention_id": intervention_id,
        "child_state": child_state,
    }, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def validate_transition(transition: StateTransition) -> None:
    """Reject synthetic ancestry whose child digest is not input-bound."""
    if not transition.counterfactual:
        raise TemporalModelError("only counterfactual transitions are validated here")
    expected = transition_digest(
        parent_state=transition.parent_state,
        block=transition.block,
        intervention_id=transition.provenance,
        child_state=transition.child_state,
    )
    if transition.child_state_digest != expected:
        raise TemporalModelError("synthetic child digest is not bound to transition inputs")


def branch_state(
    *,
    parent_state: str,
    child_state: str,
    block: int,
    proof_bound: bool,
    intervention_id: str,
    chain_id: int | None = None,
    parent_hash: str | None = None,
    parent_state_root: str | None = None,
    child_state_digest: str | None = None,
    transition_artifact_hash: str | None = None,
) -> StateTransition:
    """Create synthetic ancestry only from an authenticated parent state."""
    if not proof_bound:
        raise TemporalModelError("historical parent state is not proof-bound")
    if not parent_state or not child_state or not intervention_id:
        raise TemporalModelError("synthetic ancestry fields are incomplete")
    if any(value is None for value in (
        chain_id, parent_hash, parent_state_root,
        child_state_digest, transition_artifact_hash,
    )):
        raise TemporalModelError("temporal provenance metadata is incomplete")
    transition = StateTransition(
        block=block,
        parent_state=parent_state,
        child_state=child_state,
        provenance=intervention_id,
        counterfactual=True,
        chain_id=chain_id,
        parent_hash=parent_hash,
        parent_state_root=parent_state_root,
        child_state_digest=child_state_digest,
        transition_artifact_hash=transition_artifact_hash,
    )
    validate_transition(transition)
    return transition


def dependency_dag(
    nodes: Iterable[DependencyNode],
    edges: Iterable[DependencyEdge],
) -> tuple[DependencyNode, ...]:
    """Validate and return nodes in deterministic causal topological order."""
    node_list = list(nodes)
    node_map = {node.node_id: node for node in node_list}
    if len(node_map) != len(node_list):
        raise TemporalModelError("duplicate dependency node")
    for node in node_list:
        if not node.provenance:
            raise TemporalModelError("dependency node lacks provenance")
    edge_list = list(edges)
    incoming = {node_id: 0 for node_id in node_map}
    outgoing = {node_id: [] for node_id in node_map}
    for edge in edge_list:
        if edge.source not in node_map or edge.target not in node_map:
            raise TemporalModelError("dependency edge references unknown node")
        if not edge.relation or not edge.provenance:
            raise TemporalModelError("dependency edge lacks semantics/provenance")
        source_node = node_map[edge.source]
        target_node = node_map[edge.target]
        if source_node.block > target_node.block:
            raise TemporalModelError("dependency edge moves backwards in time")
        if source_node.chain_id is not None and target_node.chain_id is not None:
            if source_node.chain_id != target_node.chain_id:
                raise TemporalModelError("dependency edge crosses chains")
        outgoing[edge.source].append(edge.target)
        incoming[edge.target] += 1
    ready = sorted(node_id for node_id, count in incoming.items() if count == 0)
    ordered: list[DependencyNode] = []
    while ready:
        current = ready.pop(0)
        ordered.append(node_map[current])
        for target in sorted(outgoing[current]):
            incoming[target] -= 1
            if incoming[target] == 0:
                ready.append(target)
                ready.sort()
    if len(ordered) != len(node_list):
        raise TemporalModelError("dependency graph contains a cycle")
    return tuple(ordered)

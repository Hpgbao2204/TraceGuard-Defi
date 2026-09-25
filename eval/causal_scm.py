"""Trace-grounded structural causal model for E5 candidate search.

This is a typed SCM skeleton, not an automatic causal-discovery engine.  A
trace edge is evidence of data/control dependence; it is not by itself proof
of causality.  Candidates returned by :meth:`rank_candidates` require human
claim binding, a same-kind sham, and the existing replay validity gates before
they can be tested.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping


class SCMError(ValueError):
    """Invalid graph, equation, or intervention."""


Equation = Callable[[Mapping[str, Any]], Any]


@dataclass(frozen=True)
class Provenance:
    source: str
    trace_id: str | None = None
    op_index: int | None = None
    confidence: float = 1.0

    def __post_init__(self) -> None:
        if not self.source:
            raise SCMError("provenance source is required")
        if not 0.0 <= self.confidence <= 1.0:
            raise SCMError("provenance confidence must be in [0, 1]")


@dataclass(frozen=True)
class Node:
    node_id: str
    kind: str
    observed: Any = None
    equation: Equation | None = None
    interventionable: bool = False
    provenance: Provenance | None = None

    def __post_init__(self) -> None:
        allowed = {"exogenous", "context", "mechanism", "state", "outcome", "intervention"}
        if self.kind not in allowed:
            raise SCMError(f"unsupported node kind: {self.kind}")
        if not self.node_id:
            raise SCMError("node_id is required")
        if self.kind == "outcome" and self.interventionable:
            raise SCMError("outcome nodes cannot be intervention targets")


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    relation: str
    provenance: Provenance


@dataclass(frozen=True)
class Candidate:
    node_id: str
    score: float
    distance_to_outcome: int
    path_count: int
    provenance_confidence: float
    status: str = "REVIEW_REQUIRED"
    reason: str = "graph candidate only; no replay authorization"


@dataclass(frozen=True)
class Counterfactual:
    baseline: Mapping[str, Any]
    intervention: Mapping[str, Any]
    values: Mapping[str, Any]
    outcome_changed: bool


class SCM:
    """A small executable SCM over authenticated trace-grounded nodes."""

    def __init__(self, nodes: Iterable[Node], edges: Iterable[Edge]) -> None:
        self.nodes = {n.node_id: n for n in nodes}
        self.edges = list(edges)
        self._validate_edges()
        self._children = {n: [] for n in self.nodes}
        self._parents = {n: [] for n in self.nodes}
        for edge in self.edges:
            self._children[edge.source].append(edge.target)
            self._parents[edge.target].append(edge.source)
        self._order = self._topological_order()

    def _validate_edges(self) -> None:
        for edge in self.edges:
            if edge.source not in self.nodes or edge.target not in self.nodes:
                raise SCMError(f"edge references unknown node: {edge}")
            if edge.source == edge.target:
                raise SCMError(f"self-cycle at {edge.source}")

    def _topological_order(self) -> list[str]:
        indegree = {n: len(self._parents[n]) for n in self.nodes}
        # _parents is initialized lazily by __init__; use edges directly here.
        indegree = {n: 0 for n in self.nodes}
        for edge in self.edges:
            indegree[edge.target] += 1
        ready = sorted(n for n, degree in indegree.items() if degree == 0)
        order: list[str] = []
        children = {n: [] for n in self.nodes}
        for edge in self.edges:
            children[edge.source].append(edge.target)
        while ready:
            current = ready.pop(0)
            order.append(current)
            for child in sorted(children[current]):
                indegree[child] -= 1
                if indegree[child] == 0:
                    ready.append(child)
                    ready.sort()
        if len(order) != len(self.nodes):
            raise SCMError("SCM graph contains a directed cycle")
        return order

    @property
    def outcome_nodes(self) -> list[str]:
        return [n.node_id for n in self.nodes.values() if n.kind == "outcome"]

    def evaluate(self, interventions: Mapping[str, Any] | None = None) -> dict[str, Any]:
        interventions = dict(interventions or {})
        unknown = set(interventions) - self.nodes.keys()
        if unknown:
            raise SCMError(f"intervention references unknown node(s): {sorted(unknown)}")
        values: dict[str, Any] = {}
        for node_id in self._order:
            node = self.nodes[node_id]
            if node_id in interventions:
                if not node.interventionable:
                    raise SCMError(f"node is not interventionable: {node_id}")
                values[node_id] = interventions[node_id]
            elif node.equation is not None:
                values[node_id] = node.equation(values)
            else:
                values[node_id] = node.observed
        return values

    def do(self, node_id: str, value: Any, outcome: str | None = None) -> Counterfactual:
        baseline = self.evaluate()
        changed = self.evaluate({node_id: value})
        outcome_id = outcome or (self.outcome_nodes[0] if self.outcome_nodes else None)
        if outcome_id is None:
            raise SCMError("counterfactual requires an outcome node")
        if outcome_id not in baseline:
            raise SCMError(f"unknown outcome node: {outcome_id}")
        return Counterfactual(
            baseline=baseline,
            intervention={node_id: value},
            values=changed,
            outcome_changed=baseline[outcome_id] != changed[outcome_id],
        )

    def backward_slice(self, outcome: str) -> list[str]:
        if outcome not in self.nodes:
            raise SCMError(f"unknown outcome node: {outcome}")
        seen: set[str] = set()
        stack = [outcome]
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            stack.extend(self._parents[current])
        return [node_id for node_id in self._order if node_id in seen]

    def rank_candidates(self, outcome: str) -> list[Candidate]:
        sliced = set(self.backward_slice(outcome))
        candidates: list[Candidate] = []
        for node_id in sliced:
            node = self.nodes[node_id]
            if not node.interventionable or node.kind in {"outcome", "exogenous"}:
                continue
            paths = self._paths_to(outcome, node_id)
            distance = min((len(path) - 1 for path in paths), default=0)
            confidence = node.provenance.confidence if node.provenance else 0.0
            score = (1.0 / max(distance, 1)) * (0.6 + 0.4 * confidence) * min(len(paths), 3) / 3
            candidates.append(Candidate(node_id, round(score, 6), distance, len(paths), confidence))
        return sorted(candidates, key=lambda c: (-c.score, c.distance_to_outcome, c.node_id))

    def _paths_to(self, outcome: str, source: str) -> list[list[str]]:
        paths: list[list[str]] = []

        def visit(current: str, path: list[str]) -> None:
            if current == outcome:
                paths.append(path[:])
                return
            for child in self._children[current]:
                if child not in path:
                    visit(child, path + [child])

        visit(source, [source])
        return paths


def build_trace_scm(spec: Mapping[str, Any]) -> SCM:
    """Build an SCM from a JSON-like spec; equations are supplied by callers."""
    nodes = [Node(**item) for item in spec.get("nodes", [])]
    edges = [Edge(**item) for item in spec.get("edges", [])]
    return SCM(nodes, edges)
